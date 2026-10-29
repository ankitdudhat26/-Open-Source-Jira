# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Export every work item (story) of a project as a Word document, an Excel sheet or a CSV file — like Jira's
Export menu. Works the same for projects cloned from Jira (their Jira keys and fields come along) and new ones."""

# Python imports
import csv
import io
from collections import defaultdict
from html import escape

# Third party imports
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Django imports
from django.db.models import Q
from django.utils import timezone

# Module imports
from plane.db.models import (
    CustomField,
    CustomFieldValue,
    CycleIssue,
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueRelation,
    IssueType,
    JiraEntityMap,
    Label,
    Milestone,
    Module,
    ModuleIssue,
    ProjectMember,
    State,
    User,
    Cycle,
)

EXPORT_FORMATS = ("word", "excel", "csv")
PRIORITY_LABELS = {"urgent": "Urgent", "high": "High", "medium": "Medium", "low": "Low", "none": "None"}


def _person(user):
    if user is None:
        return ""
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full_name or user.display_name or user.email


def _date(value):
    return value.strftime("%Y-%m-%d") if value else ""


def _datetime(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else ""


def _custom_value(field, value, people):
    if value in (None, "", []):
        return ""
    if field.field_type == "checkbox":
        return "Yes" if value else "No"
    values = value if isinstance(value, list) else [value]
    if field.field_type == "user":
        values = [people.get(str(user_id), str(user_id)) for user_id in values]
    return ", ".join(str(item) for item in values)


# filter name -> the work item field it matches; each filter takes a list of ids (of priorities for "priority")
FIELD_FILTERS = {"type": "type_id", "state": "state_id", "priority": "priority", "milestone": "milestone_id"}
# filter name -> (link model, its field) of the filters through a link (soft-deleted links don't count)
LINK_FILTERS = {
    "assignee": (IssueAssignee, "assignee_id"),
    "label": (IssueLabel, "label_id"),
    "module": (ModuleIssue, "module_id"),
    "cycle": (CycleIssue, "cycle_id"),
}
FILTER_NAMES = ("feature", *FIELD_FILTERS, *LINK_FILTERS)


def _part_links(issue_ids):
    """(work item, its part) pairs: a work item under a Feature linked to a work item with no parent.

    Jira's "Part of" links (a story and its Backend / Frontend / QA tasks) were cloned as "relates to" links, the
    tasks having no parent of their own — they are the parts of the story, as Jira shows them.
    """
    relations = IssueRelation.objects.filter(
        Q(issue_id__in=issue_ids) | Q(related_issue_id__in=issue_ids),
        relation_type="relates_to",
        issue__deleted_at__isnull=True,
        related_issue__deleted_at__isnull=True,
    ).values_list(
        "issue_id",
        "issue__parent_id",
        "issue__type__name",
        "related_issue_id",
        "related_issue__parent_id",
        "related_issue__type__name",
    )
    pairs = set()
    for first, first_parent, first_type, second, second_parent, second_type in relations:
        for whole, whole_parent, part, part_parent, part_type in (
            (first, first_parent, second, second_parent, second_type),
            (second, second_parent, first, first_parent, first_type),
        ):
            if whole_parent and not part_parent and (part_type or "").lower() != "feature":
                pairs.add((whole, part))
    return pairs


def _feature_tree(project, feature_ids):
    """The given Features (or any parent work items) with every work item under them, at any depth — the work items
    under them and the parts of those (see _part_links)."""
    project_issues = Issue.issue_objects.filter(project=project)
    found = set(project_issues.filter(id__in=feature_ids).values_list("id", flat=True))
    level = set(found)
    while level:
        children = set(project_issues.filter(parent_id__in=level).values_list("id", flat=True))
        parts = {part for whole, part in _part_links(level) if whole in level}
        level = set(project_issues.filter(id__in=(children | parts) - found).values_list("id", flat=True))
        found |= level
    return found


def filter_work_items(issues, project, filters):
    """Narrow the work items to the ones matching every given filter (several values of one filter match any)."""
    for name, field in FIELD_FILTERS.items():
        if filters.get(name):
            issues = issues.filter(**{f"{field}__in": filters[name]})
    for name, (model, field) in LINK_FILTERS.items():
        if filters.get(name):
            linked = model.objects.filter(project=project, **{f"{field}__in": filters[name]}).values("issue_id")
            issues = issues.filter(id__in=linked)
    if filters.get("feature"):
        issues = issues.filter(id__in=_feature_tree(project, filters["feature"]))
    return issues


def export_filter_options(project, user_id=None):
    """What the work items of the project can be filtered by when exporting: id + name of each option."""
    issues = Issue.issue_objects.filter(project=project)
    if user_id is not None:
        issues = issues.filter(created_by_id=user_id)
    parent_ids = issues.filter(parent__isnull=False).values_list("parent_id", flat=True)
    features = (
        issues.filter(Q(type__name__iexact="feature") | Q(id__in=parent_ids))
        .order_by("sequence_id")
        .values_list("id", "sequence_id", "name")
    )
    members = ProjectMember.objects.filter(project=project, is_active=True).select_related("member")

    def options(rows):
        return [{"id": str(row_id), "name": name} for row_id, name in rows]

    return {
        "feature": [
            {"id": str(row_id), "name": f"{project.identifier}-{sequence_id} {name.strip()}"}
            for row_id, sequence_id, name in features
        ],
        "type": options(
            IssueType.objects.filter(id__in=issues.values_list("type_id", flat=True))
            .order_by("name")
            .values_list("id", "name")
        ),
        "state": options(State.objects.filter(project=project).order_by("sequence").values_list("id", "name")),
        "priority": [{"id": key, "name": label} for key, label in PRIORITY_LABELS.items()],
        "assignee": sorted(
            ({"id": str(member.member_id), "name": _person(member.member)} for member in members),
            key=lambda option: option["name"].lower(),
        ),
        "label": options(Label.objects.filter(project=project).order_by("name").values_list("id", "name")),
        "module": options(Module.objects.filter(project=project).order_by("name").values_list("id", "name")),
        "cycle": options(Cycle.objects.filter(project=project).order_by("-start_date").values_list("id", "name")),
        "milestone": options(Milestone.objects.filter(project=project).order_by("name").values_list("id", "name")),
    }


# relation type -> (how the work item shows it, how the other work item shows it), as Jira words its links
RELATION_LINKS = {
    "relates_to": ("Relates to", "Relates to"),
    "blocked_by": ("Is blocked by", "Blocks"),
    "duplicate": ("Duplicates", "Is duplicated by"),
    "start_before": ("Starts before", "Starts after"),
    "finish_before": ("Finishes before", "Finishes after"),
    "implemented_by": ("Is implemented by", "Implements"),
}
PART_OF, IS_PART_OF = "Part of", "Is part of"


def _issue_links(project, issues, user_id=None):
    """The links of each work item, like Jira's "Issue links": {issue id: [(link, other work item)]}.

    "Is part of" the parent and "Part of" each work item under it (and each part, see _part_links), then the
    relations ("Relates to", "Blocks"…). Only work items of the project that aren't archived, drafts or deleted — and
    with `user_id`, only the ones that user created (a client who sees only their own).
    """
    issue_ids = [issue.id for issue in issues]
    project_issues = Issue.issue_objects.filter(project=project)
    if user_id is not None:
        project_issues = project_issues.filter(created_by_id=user_id)
    links = defaultdict(list)
    for child in project_issues.filter(parent_id__in=issue_ids).order_by("sequence_id"):
        links[child.parent_id].append((PART_OF, child.id))
    for issue in issues:
        if issue.parent_id:
            links[issue.id].append((IS_PART_OF, issue.parent_id))
    parts = _part_links(issue_ids)
    for whole, part in sorted(parts, key=str):
        links[whole].append((PART_OF, part))
        links[part].append((IS_PART_OF, whole))
    relations = IssueRelation.objects.filter(
        Q(issue_id__in=issue_ids) | Q(related_issue_id__in=issue_ids),
        issue__deleted_at__isnull=True,
        related_issue__deleted_at__isnull=True,
    ).values_list("issue_id", "related_issue_id", "relation_type")
    for first, second, relation_type in relations:
        if relation_type == "relates_to" and ((first, second) in parts or (second, first) in parts):
            continue
        forward, reverse = RELATION_LINKS.get(relation_type, (relation_type, relation_type))
        links[first].append((forward, second))
        links[second].append((reverse, first))

    wanted = set(issue_ids)
    others = {
        other.id: other
        for other in project_issues.filter(
            id__in={other for item_links in links.values() for _, other in item_links}
        ).select_related("state")
    }
    identifier = project.identifier
    result = {}
    for issue_id in wanted:
        seen = set()
        rows = []
        for link, other_id in links.get(issue_id, []):
            other = others.get(other_id)
            if other is None or (link, other_id) in seen:
                continue
            seen.add((link, other_id))
            rows.append(
                {
                    "link": link,
                    "id": other_id,
                    "key": f"{identifier}-{other.sequence_id}",
                    "summary": other.name.strip(),
                    "status": other.state.name if other.state else "",
                    "sequence_id": other.sequence_id,
                }
            )
        # Jira's order: the parts, then what it is part of, then the other links — each in key order
        order = {PART_OF: 0, IS_PART_OF: 1}
        rows.sort(key=lambda row: (order.get(row["link"], 2), row["link"], row["sequence_id"]))
        result[issue_id] = rows
    return result


def _hierarchy_order(issues, links, root_ids):
    """The work items in document order from the selected Features: each followed by the work items under it."""
    by_id = {issue.id: issue for issue in issues}
    ordered, placed = [], set()

    def place(issue_id):
        if issue_id in placed or issue_id not in by_id:
            return
        placed.add(issue_id)
        ordered.append(by_id[issue_id])
        for row in links.get(issue_id, []):
            if row["link"] == PART_OF:
                place(row["id"])

    for issue in issues:
        if str(issue.id) in root_ids:
            place(issue.id)
    for issue in issues:
        place(issue.id)
    return ordered


def collect_work_items(project, user_id=None, filters=None):
    """The work items of the project in key order (a Feature export: each Feature followed by the work items under
    it), each as a dict of its exported fields.

    `user_id` limits the export to the work items that user created (clients of a project that hides the others);
    `filters` (see FILTERS) to the work items matching them. Returns (custom field names, has Jira keys, items).
    """
    issues = Issue.issue_objects.filter(project=project)
    if user_id is not None:
        issues = issues.filter(created_by_id=user_id)
    if filters:
        issues = filter_work_items(issues, project, filters)
    issues = issues.select_related("state", "type", "parent", "milestone", "created_by", "estimate_point")
    issues = list(issues.order_by("sequence_id"))
    issue_ids = [issue.id for issue in issues]
    links = _issue_links(project, issues, user_id=user_id)
    if filters and filters.get("feature"):
        issues = _hierarchy_order(issues, links, {str(feature_id) for feature_id in filters["feature"]})

    assignees = defaultdict(list)
    for record in IssueAssignee.objects.filter(issue_id__in=issue_ids).select_related("assignee"):
        assignees[record.issue_id].append(_person(record.assignee))
    labels = defaultdict(list)
    for record in IssueLabel.objects.filter(issue_id__in=issue_ids).select_related("label"):
        labels[record.issue_id].append(record.label.name)
    modules = defaultdict(list)
    for record in ModuleIssue.objects.filter(issue_id__in=issue_ids).select_related("module"):
        modules[record.issue_id].append(record.module.name)
    sprints = {
        record.issue_id: record.cycle.name
        for record in CycleIssue.objects.filter(issue_id__in=issue_ids).select_related("cycle")
    }
    comments = defaultdict(list)
    for comment in IssueComment.objects.filter(issue_id__in=issue_ids).select_related("actor").order_by("created_at"):
        comments[comment.issue_id].append(
            {"author": _person(comment.actor), "at": _datetime(comment.created_at), "html": comment.comment_html or ""}
        )
    jira_keys = dict(
        JiraEntityMap.objects.filter(
            workspace_id=project.workspace_id, entity_type="issue", plane_id__in=issue_ids
        ).values_list("plane_id", "jira_key")
    )

    fields = list(CustomField.objects.filter(project=project).order_by("sort_order", "created_at"))
    people = {
        str(user.id): _person(user)
        for user in User.objects.filter(
            id__in={
                user_id
                for value in CustomFieldValue.objects.filter(
                    issue_id__in=issue_ids, field__field_type="user"
                ).values_list("value", flat=True)
                for user_id in (value if isinstance(value, list) else [value])
                if user_id
            }
        )
    }
    custom_values = defaultdict(dict)
    fields_by_id = {field.id: field for field in fields}
    for record in CustomFieldValue.objects.filter(issue_id__in=issue_ids, field_id__in=fields_by_id):
        field = fields_by_id[record.field_id]
        custom_values[record.issue_id][field.name] = _custom_value(field, record.value, people)

    identifier = project.identifier
    items = []
    for issue in issues:
        parent = issue.parent
        items.append(
            {
                "key": f"{identifier}-{issue.sequence_id}",
                "jira_key": jira_keys.get(issue.id, ""),
                "summary": issue.name,
                "type": issue.type.name if issue.type else "",
                "status": issue.state.name if issue.state else "",
                "priority": PRIORITY_LABELS.get(issue.priority, issue.priority or ""),
                "assignees": ", ".join(assignees[issue.id]),
                "reporter": _person(issue.created_by),
                "parent": f"{identifier}-{parent.sequence_id} {parent.name}" if parent else "",
                "milestone": issue.milestone.name if issue.milestone else "",
                "modules": ", ".join(modules[issue.id]),
                "sprint": sprints.get(issue.id, ""),
                "labels": ", ".join(labels[issue.id]),
                "estimate": issue.estimate_point.value if issue.estimate_point else "",
                "start_date": _date(issue.start_date),
                "due_date": _date(issue.target_date),
                "created": _datetime(issue.created_at),
                "updated": _datetime(issue.updated_at),
                "resolved": _datetime(issue.completed_at),
                "custom": custom_values[issue.id],
                "description_html": issue.description_html or "",
                "description_text": issue.description_stripped or "",
                "comments": comments[issue.id],
                "links": links.get(issue.id, []),
                "links_text": "; ".join(f"{row['link']} {row['key']}" for row in links.get(issue.id, [])),
            }
        )
    return [field.name for field in fields], bool(jira_keys), items


# (label, item key) of the standard columns, in Jira's order
COLUMNS = [
    ("Key", "key"),
    ("Jira key", "jira_key"),
    ("Summary", "summary"),
    ("Type", "type"),
    ("Status", "status"),
    ("Priority", "priority"),
    ("Assignees", "assignees"),
    ("Reporter", "reporter"),
    ("Feature / Parent", "parent"),
    ("Milestone", "milestone"),
    ("Modules", "modules"),
    ("Sprint", "sprint"),
    ("Labels", "labels"),
    ("Issue links", "links_text"),
    ("Estimate", "estimate"),
    ("Start date", "start_date"),
    ("Due date", "due_date"),
    ("Created", "created"),
    ("Updated", "updated"),
    ("Resolved", "resolved"),
]


def _columns(has_jira_keys):
    return [column for column in COLUMNS if has_jira_keys or column[1] != "jira_key"]


def _merge_matching_custom_fields(custom_names, items):
    """A custom field named like a standard column (Jira's "Reporter") fills that column instead of repeating it.

    Its value wins: it is the one from Jira, also for people who have no account here.
    """
    standard = {label.lower(): key for label, key in COLUMNS}
    merged = [name for name in custom_names if name.lower() in standard]
    for item in items:
        for name in merged:
            value = item["custom"].pop(name, "")
            if value:
                item[standard[name.lower()]] = value
    return [name for name in custom_names if name not in merged]


def _rows(custom_names, has_jira_keys, items):
    columns = _columns(has_jira_keys)
    header = [label for label, _ in columns] + custom_names + ["Description", "Comments"]
    rows = [
        [item[key] for _, key in columns]
        + [item["custom"].get(name, "") for name in custom_names]
        + [item["description_text"], len(item["comments"])]
        for item in items
    ]
    return header, rows


def export_csv(custom_names, has_jira_keys, items):
    header, rows = _rows(custom_names, has_jira_keys, items)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    # a byte order mark, so Excel opens the file as UTF-8
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def export_excel(project, custom_names, has_jira_keys, items):
    header, rows = _rows(custom_names, has_jira_keys, items)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Work items"
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, label in enumerate(header, start=1):
        wide = label in ("Summary", "Description", "Feature / Parent")
        sheet.column_dimensions[get_column_letter(index)].width = 60 if wide else 18
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


WORD_STYLE = """
body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; color: #172B4D; }
h1 { font-size: 20pt; margin: 0 0 4pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #DFE1E6; padding-bottom: 4pt; }
h3 { font-size: 11pt; margin: 10pt 0 4pt; }
.meta { color: #5E6C84; font-size: 9pt; margin-bottom: 12pt; }
table.fields { border-collapse: collapse; width: 100%; }
table.fields td { border: 1px solid #DFE1E6; padding: 3pt 6pt; vertical-align: top; font-size: 10pt; }
table.fields td.label { background: #F4F5F7; font-weight: bold; width: 28%; }
.comment { border-left: 3px solid #DFE1E6; padding-left: 8pt; margin: 6pt 0; }
.comment .by { color: #5E6C84; font-size: 9pt; }
table.links { border-collapse: collapse; width: 100%; }
table.links td { border: none; padding: 1pt 6pt 1pt 0; font-size: 10pt; vertical-align: top; }
table.links td.links-heading { font-weight: bold; padding-top: 2pt; }
"""


def _work_item_url(app_url, project, key):
    """Where the work item opens in the app (its key, like a Jira issue link)."""
    return f"{app_url.rstrip('/')}/{project.workspace.slug}/browse/{key}/" if app_url else ""


def _word_links(project, links, app_url, nested_links):
    """Jira's "Issue links" box: a heading per kind of link, then one row per linked work item, its key opening it.

    `nested_links` has the links of the work items listed only here (see _listed_parts): their parts follow them,
    indented — a Feature's stories, each with its tasks.
    """
    rows = []
    heading = None

    def add(row, depth, seen):
        key = escape(row["key"])
        url = _work_item_url(app_url, project, row["key"])
        key_html = f'<a href="{escape(url)}">{key}</a>' if url else key
        summary = row["summary"] if len(row["summary"]) <= 60 else f"{row['summary'][:57]}..."
        indent = f' style="padding-left: {depth * 14}pt"' if depth else ""
        rows.append(
            f"<tr><td{indent}>{escape(row['link'])}</td><td>{key_html}</td>"
            f"<td>{escape(summary)}</td><td>{escape(row['status'])}</td></tr>"
        )
        if row["link"] != PART_OF or row["key"] in seen:
            return
        for part in nested_links.get(row["key"], []):
            if part["link"] == PART_OF:
                add(part, depth + 1, seen | {row["key"]})

    for row in links:
        kind = "Part of" if row["link"] in (PART_OF, IS_PART_OF) else row["link"]
        if kind != heading:
            heading = kind
            rows.append(f'<tr><td colspan="4" class="links-heading">{escape(kind)}</td></tr>')
        add(row, 0, set())
    return f'<table class="links">{"".join(rows)}</table>'


def _listed_parts(items):
    """The keys of the work items listed in the "Part of" links of another exported work item — a Feature's stories,
    a story's tasks. They are shown there, not again on their own (a work item part of nothing exported keeps its
    own section)."""
    keys = {item["key"] for item in items}
    parts = {item["key"]: [row["key"] for row in item["links"] if row["link"] == PART_OF] for item in items}
    roots = [
        item["key"]
        for item in items
        if not any(row["link"] == IS_PART_OF and row["key"] in keys for row in item["links"])
    ]
    listed, pending = set(), list(roots)
    while pending:
        for part in parts.get(pending.pop(), []):
            if part in keys and part not in listed and part not in roots:
                listed.add(part)
                pending.append(part)
    return listed


def export_word(project, custom_names, has_jira_keys, items, app_url=None):
    """A Word document (HTML that Word opens, the way Jira exports to Word): one section per work item, the work items
    that are part of another one listed in its "Issue links" instead."""
    columns = [column for column in _columns(has_jira_keys) if column[1] not in ("key", "summary", "links_text")]
    listed = _listed_parts(items)
    nested_links = {item["key"]: item["links"] for item in items if item["key"] in listed}
    items = [item for item in items if item["key"] not in listed]
    listed_count = f" · {len(listed)} more listed in their issue links" if listed else ""
    item_count = f"{len(items)} work item{'' if len(items) == 1 else 's'}"
    parts = [
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"'
        ' xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8">',
        f"<title>{escape(project.name)} work items</title><style>{WORD_STYLE}</style></head><body>",
        f"<h1>{escape(project.name)}</h1>",
        f'<div class="meta">{item_count}{listed_count} · exported {_datetime(timezone.now())}</div>',
    ]
    for item in items:
        key, url = escape(item["key"]), _work_item_url(app_url, project, item["key"])
        key_html = f'<a href="{escape(url)}">{key}</a>' if url else key
        parts.append(f"<h2>[{key_html}] {escape(item['summary'])}</h2>")
        parts.append('<table class="fields">')
        values = [(label, item[key]) for label, key in columns] + [
            (name, item["custom"].get(name, "")) for name in custom_names
        ]
        for label, value in values:
            if value in ("", None) or (label == "Jira key" and value == item["key"]):
                continue
            parts.append(f'<tr><td class="label">{escape(label)}</td><td>{escape(str(value))}</td></tr>')
        if item["links"]:
            links_html = _word_links(project, item["links"], app_url, nested_links)
            parts.append(f'<tr><td class="label">Issue links</td><td>{links_html}</td></tr>')
        parts.append("</table>")
        if item["description_html"].strip() and item["description_text"].strip():
            # the description is stored sanitized when the work item is saved
            parts.append(f"<h3>Description</h3>{item['description_html']}")
        if item["comments"]:
            parts.append(f"<h3>Comments ({len(item['comments'])})</h3>")
            for comment in item["comments"]:
                parts.append(
                    f'<div class="comment"><div class="by">{escape(comment["author"])} · {escape(comment["at"])}</div>'
                    f"{comment['html']}</div>"
                )
    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")


def export_work_items(project, export_format, user_id=None, filters=None, app_url=None):
    """Returns (file bytes, content type, file name) of the project's work items in the given format.

    `app_url` (the web app) makes the keys in the Word document links that open the work items."""
    custom_names, has_jira_keys, items = collect_work_items(project, user_id=user_id, filters=filters)
    custom_names = _merge_matching_custom_fields(custom_names, items)
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    name = f"{project.identifier}-work-items-{stamp}"
    if export_format == "word":
        return (
            export_word(project, custom_names, has_jira_keys, items, app_url=app_url),
            "application/msword",
            f"{name}.doc",
        )
    if export_format == "excel":
        return (
            export_excel(project, custom_names, has_jira_keys, items),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{name}.xlsx",
        )
    return export_csv(custom_names, has_jira_keys, items), "text/csv; charset=utf-8", f"{name}.csv"
