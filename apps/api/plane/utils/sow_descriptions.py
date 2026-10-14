# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Descriptions for work items imported from a SOW.

Built from what the project already knows about the work item (its feature, module, milestone, task type and
resource), so they can be generated at import time and backfilled for projects imported earlier. A description
someone has written or edited is never overwritten.
"""

# Python imports
import html
import re
from html.parser import HTMLParser

# Module imports
from plane.db.models import Issue, IssueLabel, ModuleIssue, ProjectResource

TASK_TYPE_GROUP = "Task Type"

# What "done" means for each task type of the SOW template
DONE_WHEN = {
    "planning": [
        "Requirements walked through with the client",
        "Plan and timeline shared and agreed",
    ],
    "architecture": [
        "Design documented and reviewed by the team",
        "Approved by the client",
    ],
    "devops": [
        "Environment set up and reachable by the team",
        "Configuration and access documented",
    ],
    "integration": [
        "Integration works end to end in the sandbox / staging",
        "Webhooks, errors and retries handled",
        "Credentials kept in environment configuration",
    ],
    "backend api": [
        "Endpoints implemented with validation and error handling",
        "API documented",
        "Unit tests added and passing",
        "Deployed to staging",
    ],
    "web frontend": [
        "Screens match the approved designs (EN and Arabic RTL where applicable)",
        "Connected to the APIs with loading, empty and error states",
        "Responsive on mobile and desktop browsers",
        "Deployed to staging",
    ],
    "mobile (flutter)": [
        "Screens match the approved designs (EN and Arabic RTL)",
        "Connected to the APIs with loading, empty and error states",
        "Tested on supported Android versions",
        "Included in the staging APK",
    ],
    "design": [
        "Designs follow the style guide",
        "English and Arabic RTL variants where applicable",
        "Reviewed and approved by the client",
    ],
    "prototype": [
        "Clickable prototype covers the main flows",
        "Reviewed and approved by the client",
    ],
    "qa": [
        "Test cases written for the feature",
        "Test cases executed and results recorded",
        "Defects logged as bugs and re-tested after fixing",
    ],
    "bug fix": [
        "Reported defects fixed",
        "Fixes verified by QA",
    ],
    "aso": [
        "Store listing content prepared",
        "Reviewed and approved by the client",
    ],
}
DEFAULT_DONE_WHEN = ["Work completed as described above", "Reviewed and verified"]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def feature_scope(feature):
    """The feature's own SOW details: the first paragraph of its description."""
    match = re.match(r"\s*<p[^>]*>(.*?)</p>", feature.description_html or "", re.S)
    if not match:
        return (feature.description_stripped or "").strip()
    extractor = _TextExtractor()
    extractor.feed(match.group(1))
    return "".join(extractor.parts).strip()


def is_empty_description(issue):
    return not (issue.description_stripped or "").strip()


def _p(text):
    return f"<p>{html.escape(text)}</p>"


def _item(label, text):
    return f"<li><p><strong>{html.escape(label)}:</strong> {html.escape(text)}</p></li>"


def _module(issue):
    module_issue = (
        ModuleIssue.objects.filter(issue=issue, module__deleted_at__isnull=True).select_related("module").first()
    )
    return module_issue.module if module_issue else None


def _milestone_text(milestone):
    if milestone is None:
        return None
    name = f"{milestone.code} · {milestone.name}" if milestone.code else milestone.name
    return f"{name} — {milestone.description}" if milestone.description else name


def build_task_description(task):
    """Description of a task (or bug) under a feature."""
    feature = task.parent
    labels = list(IssueLabel.objects.filter(issue=task).select_related("label", "label__parent"))
    task_type = next(
        (row.label.name for row in labels if row.label.parent and row.label.parent.name == TASK_TYPE_GROUP), None
    )
    resource = (
        ProjectResource.objects.filter(project_id=task.project_id, label_id__in=[row.label_id for row in labels])
        .select_related("member")
        .first()
    )
    module = _module(task)

    intro = task.name
    if feature is not None:
        intro = f"{task.name} for the “{feature.name}” feature"
        if module is not None:
            intro += f" of the {module.name} module"
    parts = [_p(f"{intro}.")]

    details = []
    scope = feature_scope(feature) if feature is not None else ""
    if scope:
        details.append(_item("Feature scope", scope))
    if module is not None and module.description:
        details.append(_item("Module scope", module.description))
    if task_type:
        details.append(_item("Task type", task_type))
    if resource is not None:
        role = f"{resource.code} · {resource.role}" if resource.code else resource.role
        details.append(_item("Resource", f"{role}{' — ' + resource.responsibilities if resource.responsibilities else ''}"))
    milestone_text = _milestone_text(task.milestone)
    if milestone_text:
        details.append(_item("Milestone", milestone_text))
    if task.external_source == "sow" and task.external_id:
        details.append(_item("SOW reference", f"{task.external_id}" + (f" (feature {feature.external_id})" if feature and feature.external_id else "")))
    if details:
        parts.append("<h3>Details</h3>")
        parts.append(f"<ul>{''.join(details)}</ul>")

    done_when = DONE_WHEN.get((task_type or "").lower(), DEFAULT_DONE_WHEN)
    parts.append("<h3>Done when</h3>")
    parts.append(f"<ul>{''.join(f'<li><p>{html.escape(item)}</p></li>' for item in done_when)}</ul>")
    return "".join(parts)


def build_feature_description(feature, details):
    """Description of a feature: its SOW details plus where it is delivered and the tasks that build it."""
    module = _module(feature)
    parts = [_p(details)] if details else []

    items = []
    if module is not None:
        items.append(_item("Module", f"{module.name}{' — ' + module.description if module.description else ''}"))
    milestone_text = _milestone_text(feature.milestone)
    if milestone_text:
        items.append(_item("Completed in milestone", milestone_text))
    if feature.external_source == "sow" and feature.external_id:
        items.append(_item("SOW reference", feature.external_id))
    if items:
        parts.append("<h3>Details</h3>")
        parts.append(f"<ul>{''.join(items)}</ul>")

    tasks = list(Issue.issue_objects.filter(parent=feature).order_by("sequence_id").values_list("name", flat=True))
    if tasks:
        parts.append("<h3>Tasks</h3>")
        parts.append(f"<ul>{''.join(f'<li><p>{html.escape(name)}</p></li>' for name in tasks)}</ul>")
    return "".join(parts)


def fill_sow_descriptions(project, feature_details=None):
    """Write descriptions for the SOW work items of a project that have none (or only the raw SOW details).

    feature_details: optional {feature SOW ID: details} from the SOW file; otherwise the current text is used.
    Returns the number of work items updated.
    """
    updated = 0
    tasks = Issue.issue_objects.filter(project=project, external_source="sow", type__external_id="task")
    for task in tasks.select_related("parent", "milestone"):
        if not is_empty_description(task):
            continue
        task.description_html = build_task_description(task)
        task.description_binary = None
        task.save()
        updated += 1
    features = Issue.issue_objects.filter(project=project, external_source="sow", type__external_id="feature")
    for feature in features.select_related("milestone"):
        current = (feature.description_stripped or "").strip()
        details = (feature_details or {}).get(feature.external_id) or feature_scope(feature)
        # only replace an empty description or the bare SOW details written by an earlier import
        if current and current != details:
            continue
        feature.description_html = build_feature_description(feature, details)
        feature.description_binary = None
        feature.save()
        updated += 1

    return updated
