# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The client's side of a project's Intake link, beyond their requests: the project's work items (the same list the
team sees), a work item's details with its comments, files and history, the states they may move it to, and what
happened to their requests and work items (their notifications)."""

from django.db.models import Q

from plane.db.models import (
    FileAsset,
    Issue,
    IssueActivity,
    IssueComment,
    IntakeIssue,
    ProjectWorkflow,
    State,
    StateGroup,
    WorkflowTransition,
)
from plane.utils.intake_form import STATUS_LABELS, type_color

# fields of the work item history shown to the client (the rest is the team's own bookkeeping)
HISTORY_FIELDS = {
    None,
    "state",
    "priority",
    "assignees",
    "labels",
    "name",
    "description",
    "start_date",
    "target_date",
    "comment",
    "attachment",
    "intake",
    "parent",
    "type",
}


MAX_NAME_LENGTH = 255


def clean_full_name(full_name):
    """A full name as typed (extra spaces dropped), or "" when it is empty."""
    return " ".join(str(full_name or "").split())[: MAX_NAME_LENGTH * 2]


def set_full_name(user, full_name):
    """Save the client's full name: the first word is the first name, the rest the last name."""
    name = clean_full_name(full_name)
    if not name:
        return False
    first, _, last = name.partition(" ")
    user.first_name, user.last_name = first[:MAX_NAME_LENGTH], last[:MAX_NAME_LENGTH]
    user.save(update_fields=["first_name", "last_name"])
    return True


def user_name(user):
    if user is None:
        return ""
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.display_name or user.email


def visible_work_items(user, projects):
    """The work items of the client's projects — the same list the team sees on the project's Work items (not drafts,
    archived ones or requests still waiting in Intake)."""
    return (
        Issue.issue_objects.filter(project__in=projects)
        .select_related("project", "state", "type", "parent", "parent__project", "milestone", "created_by")
        .prefetch_related("assignees", "labels", "issue_module__module", "issue_cycle__cycle")
        .order_by("-created_at")
    )


def _state(state):
    if state is None:
        return None
    return {"id": str(state.id), "name": state.name, "color": state.color, "group": state.group}


def work_item_row(issue, user=None):
    """A work item as the client's list shows it; ``is_mine`` marks the ones the client created (their requests)."""
    return {
        "id": str(issue.id),
        "project_id": str(issue.project_id),
        "project_name": issue.project.name,
        "key": f"{issue.project.identifier}-{issue.sequence_id}",
        "name": issue.name,
        "type": {"name": issue.type.name, "color": type_color(issue.type.logo_props)} if issue.type else None,
        "state": _state(issue.state),
        "priority": issue.priority,
        "assignees": [{"id": str(user.id), "name": user_name(user)} for user in issue.assignees.all()],
        "labels": [{"id": str(label.id), "name": label.name, "color": label.color} for label in issue.labels.all()],
        "start_date": issue.start_date,
        "target_date": issue.target_date,
        "modules": [
            {"id": str(link.module_id), "name": link.module.name}
            for link in issue.issue_module.all()
            if link.deleted_at is None and link.module.deleted_at is None
        ],
        "sprint": next(
            (
                {"id": str(link.cycle_id), "name": link.cycle.name}
                for link in issue.issue_cycle.all()
                if link.deleted_at is None and link.cycle.deleted_at is None
            ),
            None,
        ),
        "parent": (
            {
                "id": str(issue.parent_id),
                "key": f"{issue.parent.project.identifier}-{issue.parent.sequence_id}",
                "name": issue.parent.name,
            }
            if issue.parent_id and issue.parent
            else None
        ),
        "milestone": {"id": str(issue.milestone_id), "name": issue.milestone.name} if issue.milestone_id else None,
        "created_by": (
            {"id": str(issue.created_by_id), "name": user_name(issue.created_by)} if issue.created_by_id else None
        ),
        "is_mine": user is not None and issue.created_by_id == user.id,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


def allowed_states(issue, user):
    """The states the client may move the work item to: the project's workflow decides, like for the team (a step
    with reviewers is only for them). Without rules from the current state, any state."""
    states = (
        State.objects.filter(project_id=issue.project_id).exclude(group=StateGroup.TRIAGE.value).order_by("sequence")
    )
    enabled = ProjectWorkflow.objects.filter(project_id=issue.project_id, is_enabled=True).exists()
    rules = (
        list(
            WorkflowTransition.objects.filter(
                project_id=issue.project_id, from_state_id=issue.state_id, to_state__deleted_at__isnull=True
            )
        )
        if enabled
        else []
    )
    if not rules:
        return [_state(state) for state in states if state.id != issue.state_id]
    permitted = {
        rule.to_state_id
        for rule in rules
        if not rule.reviewer_ids or str(user.id) in {str(reviewer) for reviewer in rule.reviewer_ids}
    }
    return [_state(state) for state in states if state.id in permitted]


def activity_text(activity):
    """One line of history, as the app words it."""
    field, verb = activity.field, activity.verb
    if field is None and verb == "created":
        return "created the work item"
    if field == "intake":
        return f"marked the request {activity.new_value or ''}".strip()
    if field == "state":
        return f"moved it from {activity.old_value} to {activity.new_value}"
    if field == "comment":
        return "commented" if verb == "created" else f"{verb} a comment"
    if field == "attachment":
        return "attached a file" if verb == "created" else "removed a file"
    text = (activity.comment or f"updated the {field}").strip()
    value = activity.new_value or activity.old_value or ""
    return f"{text} {value}".strip()


def work_item_detail(issue, user, storage):
    files = FileAsset.objects.filter(
        issue_id=issue.id, entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT, is_uploaded=True
    ).order_by("-created_at")
    comments = IssueComment.objects.filter(issue_id=issue.id).select_related("actor").order_by("created_at")
    history = (
        IssueActivity.objects.filter(issue_id=issue.id)
        .filter(Q(field__in=[field for field in HISTORY_FIELDS if field]) | Q(field__isnull=True, verb="created"))
        .exclude(field="comment")
        .select_related("actor")
        .order_by("created_at")
    )
    states = State.objects.filter(project_id=issue.project_id).exclude(group=StateGroup.TRIAGE.value)
    return {
        **work_item_row(issue, user),
        # every state of the project, so the history draws a change of state with its colours
        "states": [_state(state) for state in states],
        "description_html": issue.description_html or "",
        "allowed_states": allowed_states(issue, user),
        "attachments": [
            {
                "id": str(asset.id),
                "name": (asset.attributes or {}).get("name") or "file",
                "size": asset.size,
                "created_at": asset.created_at,
                "url": storage.generate_presigned_url(
                    object_name=str(asset.asset), filename=(asset.attributes or {}).get("name")
                ),
            }
            for asset in files
        ],
        "comments": [
            {
                "id": str(comment.id),
                "author": user_name(comment.actor),
                "is_mine": comment.actor_id == user.id,
                "comment_html": comment.comment_html,
                "created_at": comment.created_at,
            }
            for comment in comments
        ],
        "history": [
            {
                "id": str(activity.id),
                "actor": user_name(activity.actor),
                "field": activity.field,
                "verb": activity.verb,
                "old_value": activity.old_value,
                "new_value": activity.new_value,
                "text": activity_text(activity),
                "created_at": activity.created_at,
            }
            for activity in history
        ],
    }


def notifications(user, projects, limit=50):
    """What happened to the client's requests and work items, newest first: the team's decisions on requests, and
    what others did on the work items they created (state, comments, files, assignees, dates)."""
    project_ids = [project.id for project in projects]
    events = []
    for request in (
        IntakeIssue.objects.filter(created_by=user, project_id__in=project_ids, issue__deleted_at__isnull=True)
        .exclude(status=-2)
        .select_related("issue", "project")
        .order_by("-updated_at")[:limit]
    ):
        key = f"{request.project.identifier}-{request.issue.sequence_id}"
        label = STATUS_LABELS.get(request.status, "updated").lower()
        reason = (request.extra or {}).get("decline_reason", "")
        events.append(
            {
                "id": f"request-{request.id}",
                "kind": f"request_{label}",
                "issue_id": str(request.issue_id) if request.status == 1 else None,
                "key": key,
                "title": request.issue.name,
                "text": f"Your request was {label}" + (f": {reason}" if reason and request.status == -1 else "."),
                "created_at": request.updated_at,
            }
        )
    activities = (
        IssueActivity.objects.filter(
            issue__created_by=user,
            issue__project_id__in=project_ids,
            issue__deleted_at__isnull=True,
            field__in=["state", "comment", "attachment", "assignees", "priority", "target_date", "start_date"],
        )
        .exclude(actor=user)
        .select_related("actor", "issue", "issue__project")
        .order_by("-created_at")[:limit]
    )
    for activity in activities:
        issue = activity.issue
        events.append(
            {
                "id": f"activity-{activity.id}",
                "kind": activity.field,
                "issue_id": str(issue.id),
                "key": f"{issue.project.identifier}-{issue.sequence_id}",
                "title": issue.name,
                "text": f"{user_name(activity.actor)} {activity_text(activity)}",
                "created_at": activity.created_at,
            }
        )
    events.sort(key=lambda event: event["created_at"], reverse=True)
    return events[:limit]
