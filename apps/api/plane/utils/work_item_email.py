# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Jira style notification email for one work item and one recipient.

The activity logged for a work item within one batch (a minute) becomes a single email with:
* a headline written for the recipient ("Asha assigned SALES-12 to you", "Ravi commented on SALES-12", ...),
* a summary card of the work item (type, status, priority, assignees, sprint, dates),
* every change as "old -> new" grouped by the person who made it, in time order,
* the full text of new comments,
* a footer saying why the recipient gets the email.
"""

from datetime import datetime
from email.utils import make_msgid
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.conf import settings

from plane.db.models import CycleIssue, IssueAssignee, User

FIELD_LABELS = {
    "name": "Title",
    "state": "Status",
    "priority": "Priority",
    "assignees": "Assignee",
    "labels": "Labels",
    "start_date": "Start date",
    "target_date": "Due date",
    "parent": "Parent",
    "cycles": "Sprint",
    "modules": "Module",
    "estimate_point": "Estimate",
    "estimate_points": "Estimate",
    "estimate_categories": "Estimate",
    "type": "Type",
    "milestone": "Milestone",
    "queue": "Queue",
    "link": "Link",
    "attachment": "Attachment",
    "blocking": "Blocks",
    "blocked_by": "Blocked by",
    "duplicate": "Duplicates",
    "relates_to": "Relates to",
    "start_before": "Starts before",
    "start_after": "Starts after",
    "finish_before": "Finishes before",
    "finish_after": "Finishes after",
    "archived_at": "Archived",
    "description": "Description",
}

# fields where each activity adds or removes one value
LIST_FIELDS = {
    "assignees",
    "labels",
    "cycles",
    "modules",
    "link",
    "attachment",
    "blocking",
    "blocked_by",
    "duplicate",
    "relates_to",
    "start_before",
    "start_after",
    "finish_before",
    "finish_after",
}
DATE_FIELDS = {"start_date", "target_date"}
EMPTY_VALUES = {"", "None", "none", "null"}


def _blank(value):
    return value is None or str(value).strip() in EMPTY_VALUES


def _format_value(field, value):
    if _blank(value):
        return ""
    value = str(value)
    if field in DATE_FIELDS:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return value
    if field == "priority":
        return value.capitalize()
    if field == "attachment":
        # the activity keeps the storage path; show the file name
        return value.rstrip("/").rsplit("/", 1)[-1]
    return value


def _person(user):
    if user is None:
        return {"name": "Someone", "initial": "?"}
    name = " ".join(part for part in [user.first_name, user.last_name] if part).strip() or user.display_name
    return {"name": name or user.email, "initial": (name or user.email or "?")[0].upper()}


def _local_time(value, timezone_name):
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(zone).strftime("%d %b %Y, %I:%M %p").replace(" 0", " ")


def comment_html_for_email(html):
    """Editor HTML made safe to show in an email: mentions become @name, scripts and styles are dropped."""
    if _blank(html):
        return ""
    soup = BeautifulSoup(str(html), "html.parser")
    for tag in soup(["script", "style", "iframe", "object", "embed"]):
        tag.decompose()
    mention_ids = [tag.get("entity_identifier") for tag in soup.find_all("mention-component")]
    users = {str(user.id): user for user in User.objects.filter(pk__in=[i for i in mention_ids if i])}
    for tag in soup.find_all("mention-component"):
        user = users.get(str(tag.get("entity_identifier")))
        tag.replace_with(f"@{user.display_name}" if user else "@someone")
    for tag in soup.find_all(True):
        # inline handlers / editor attributes are not needed in an email
        for attribute in list(tag.attrs):
            if attribute.startswith("on") or attribute in {"class", "data-id", "style"}:
                del tag.attrs[attribute]
    return str(soup)


def _flatten(notification_data):
    """[(actor_id, activity dict)] in the order things happened."""
    entries = []
    for actor_id, items in notification_data.items():
        for item in items:
            activity = (item or {}).get("issue_activity") or {}
            entries.append((str(actor_id), activity))
    return sorted(entries, key=lambda entry: str(entry[1].get("activity_time") or ""))


def _new_block(actor, when):
    return {"actor": actor, "time": when, "created": False, "changes": {}, "comments": [], "mentions": []}


def build_events(notification_data, receiver, timezone_name):
    """Group the activity into blocks of consecutive actions by the same person (like Jira's email)."""
    entries = _flatten(notification_data)
    actors = {str(user.id): user for user in User.objects.filter(pk__in={actor for actor, _ in entries})}
    blocks = []
    flags = {"created": False, "assigned_to_you": False, "mentioned": False, "comments": 0, "changes": 0}
    seen_comments = set()
    for actor_id, activity in entries:
        field = activity.get("field")
        field = None if _blank(field) else field
        verb = activity.get("verb")
        when = _local_time(activity.get("activity_time"), timezone_name)
        if not blocks or blocks[-1]["actor_id"] != actor_id:
            blocks.append({"actor_id": actor_id, **_new_block(_person(actors.get(actor_id)), when)})
        block = blocks[-1]

        if field is None and verb == "created":
            block["created"] = True
            flags["created"] = True
        elif field in {"comment", "mention"}:
            source = activity.get("source")
            is_description_mention = field == "mention" and source == "description"
            if field == "mention":
                flags["mentioned"] = True
            if is_description_mention:
                block["mentions"].append("mentioned you in the description")
                continue
            if verb == "deleted":
                block["mentions"].append("deleted a comment")
                continue
            html = comment_html_for_email(activity.get("new_value"))
            key = (activity.get("id"), html)
            if not html or key in seen_comments:
                continue
            seen_comments.add(key)
            block["comments"].append({"html": html, "edited": verb == "updated", "mention": field == "mention"})
            flags["comments"] += 1
        else:
            label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
            if field == "assignees" and str(activity.get("new_identifier")) == str(receiver.id):
                flags["assigned_to_you"] = True
            if field == "description":
                block["changes"].setdefault(field, {"label": label, "text": "updated the description"})
                continue
            old_value = _format_value(field, activity.get("old_value"))
            new_value = _format_value(field, activity.get("new_value"))
            change = block["changes"].setdefault(field, {"label": label, "old": old_value, "added": [], "removed": []})
            if field in LIST_FIELDS:
                if new_value and new_value not in change["added"]:
                    if new_value in change["removed"]:
                        change["removed"].remove(new_value)
                    else:
                        change["added"].append(new_value)
                if old_value and old_value != new_value and old_value not in change["removed"]:
                    if old_value in change["added"]:
                        change["added"].remove(old_value)
                    else:
                        change["removed"].append(old_value)
            else:
                # several edits of one field in the batch: first old value -> last new value
                change["new"] = new_value

    for block in blocks:
        rows = []
        for field, change in block["changes"].items():
            if "text" in change:
                rows.append({"label": change["label"], "text": change["text"]})
            elif field in LIST_FIELDS:
                if change["added"] or change["removed"]:
                    rows.append({"label": change["label"], "added": change["added"], "removed": change["removed"]})
            elif change.get("old") != change.get("new"):
                rows.append(
                    {"label": change["label"], "old": change.get("old") or "None", "new": change.get("new") or "None"}
                )
        block["rows"] = rows
        flags["changes"] += len(rows)
    blocks = [block for block in blocks if block["created"] or block["rows"] or block["comments"] or block["mentions"]]
    return blocks, flags


def _headline(blocks, flags, key):
    actor_names = list(dict.fromkeys(block["actor"]["name"] for block in blocks))
    first = actor_names[0] if actor_names else "Someone"
    if flags["created"]:
        return f"{first} created {key}" + (" and assigned it to you" if flags["assigned_to_you"] else "")
    if flags["assigned_to_you"]:
        return f"{first} assigned {key} to you"
    if flags["mentioned"]:
        return f"{first} mentioned you on {key}"
    if flags["comments"] and not flags["changes"]:
        if len(actor_names) > 1 or flags["comments"] > 1:
            return f"{flags['comments']} new comments on {key}"
        return f"{first} commented on {key}"
    if len(actor_names) > 1:
        others = len(actor_names) - 1
        return f"{first} and {others} {'other' if others == 1 else 'others'} updated {key}"
    return f"{first} updated {key}"


def _reason(issue, receiver):
    if IssueAssignee.objects.filter(issue=issue, assignee=receiver).exists():
        return "You're receiving this because you're assigned to this work item."
    if issue.created_by_id == receiver.id:
        return "You're receiving this because you created this work item."
    return "You're receiving this because you're watching this work item."


def _summary(issue):
    assignees = [
        _person(record.assignee)["name"]
        for record in IssueAssignee.objects.filter(issue=issue).select_related("assignee").order_by("created_at")
    ]
    cycle = CycleIssue.objects.filter(issue=issue).select_related("cycle").first()
    rows = [
        ("Type", issue.type.name if issue.type_id else ""),
        ("Status", issue.state.name if issue.state_id else ""),
        ("Priority", _format_value("priority", issue.priority)),
        ("Assignee", ", ".join(assignees) or "Unassigned"),
        ("Sprint", cycle.cycle.name if cycle else ""),
        ("Milestone", issue.milestone.name if issue.milestone_id else ""),
        ("Due date", _format_value("target_date", issue.target_date)),
        (
            "Parent",
            f"{issue.project.identifier}-{issue.parent.sequence_id} {issue.parent.name}" if issue.parent_id else "",
        ),
    ]
    return [{"label": label, "value": value} for label, value in rows if value]


def unwatch_url(issue, receiver, base_url):
    """One click "Stop watching" link. The API lives at WEB_URL (same host as the app in production)."""
    from plane.app.views.issue.unwatch import make_unwatch_token

    api_url = (settings.WEB_URL or base_url).rstrip("/")
    return f"{api_url}/api/notifications/unwatch/{make_unwatch_token(receiver.id, issue.id)}/"


def get_brand_name():
    """Product name in the subject ("[HLIS Flow] (SALES-12) ...")."""
    return settings.BRAND_NAME


def thread_headers(issue, email_from):
    """Message headers that make every email about one work item one conversation (Gmail, Outlook, ...)."""
    domain = (email_from or "").rsplit("@", 1)[-1].strip(" >") or "plane.local"
    thread_id = f"<work-item-{issue.id}@{domain}>"
    return {"Message-ID": make_msgid(domain=domain), "In-Reply-To": thread_id, "References": thread_id}


def build_work_item_email(issue, receiver, notification_data, base_url, brand):
    """Subject and template context for one recipient, or None when nothing is worth an email."""
    timezone_name = receiver.user_timezone or "UTC"
    blocks, flags = build_events(notification_data, receiver, timezone_name)
    if not blocks:
        return None
    key = f"{issue.project.identifier}-{issue.sequence_id}"
    slug = issue.project.workspace.slug
    issue_url = f"{base_url}/{slug}/projects/{issue.project_id}/issues/{issue.id}"
    return {
        "subject": f"[{brand}] ({key}) {issue.name}",
        "context": {
            "brand": brand,
            "headline": _headline(blocks, flags, key),
            "key": key,
            "issue_name": issue.name,
            "project_name": issue.project.name,
            "workspace_slug": slug,
            "summary": _summary(issue),
            "blocks": blocks,
            "issue_url": issue_url,
            "comment_url": f"{issue_url}#comments",
            "preferences_url": f"{base_url}/{slug}/settings/account/notifications/",
            "unwatch_url": unwatch_url(issue, receiver, base_url),
            "reason": _reason(issue, receiver),
            "receiver_email": receiver.email,
        },
    }
