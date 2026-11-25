# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The JSON shapes of the external API. Plain functions (not DRF serializers) so every field is explicit and the
documentation (apps/api/docs/external-api/README.md) can list them one to one."""

# Django imports
from django.db.models import Prefetch, Q

# Module imports
from plane.db.models import (
    CommentReaction,
    CustomFieldValue,
    CycleIssue,
    FileAsset,
    IntakeIssue,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLink,
    IssueReaction,
    IssueRelation,
    IssueSubscriber,
    IssueLabel,
    ModuleIssue,
    QueueItem,
    User,
)
from plane.utils.intake_form import type_color
from plane.utils.uuid import is_valid_uuid

PRIORITY_LABELS = {"urgent": "Urgent", "high": "High", "medium": "Medium", "low": "Low", "none": "None"}
INTAKE_STATUS = {-2: "pending", -1: "declined", 0: "snoozed", 1: "accepted", 2: "duplicate"}


def iso(value):
    return value.isoformat() if value else None


def user_brief(user):
    if user is None:
        return None
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return {
        "id": str(user.id),
        "name": full or user.display_name or user.email,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url or None,
    }


def state_brief(state):
    if state is None:
        return None
    return {"id": str(state.id), "name": state.name, "group": state.group, "color": state.color}


def type_brief(issue_type):
    if issue_type is None:
        return None
    return {"id": str(issue_type.id), "name": issue_type.name, "color": type_color(issue_type.logo_props)}


def project_brief(project):
    return {
        "id": str(project.id),
        "name": project.name,
        "identifier": project.identifier,
        "workspace": {"id": str(project.workspace_id), "slug": project.workspace.slug, "name": project.workspace.name},
    }


def project_row(project, membership_role):
    return {
        **project_brief(project),
        "description": project.description or "",
        "project_type": project.project_type,
        "network": "public" if project.network == 2 else "private",
        "lead": user_brief(project.project_lead),
        "your_role": {20: "admin", 15: "member", 5: "guest"}.get(membership_role, "member"),
        "logo_props": project.logo_props or {},
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


# ---- work items -------------------------------------------------------------------------------------------------


def work_items_queryset(project):
    """The project's work items as the app lists them (no drafts, archived ones or requests still in Intake), with what
    a row needs loaded in a few queries."""
    return (
        Issue.issue_objects.filter(project=project)
        .select_related(
            "project",
            "project__workspace",
            "state",
            "type",
            "parent",
            "parent__project",
            "milestone",
            "created_by",
            "updated_by",
            "estimate_point",
        )
        .prefetch_related(
            Prefetch(
                "issue_assignee",
                queryset=IssueAssignee.objects.filter(deleted_at__isnull=True).select_related("assignee"),
                to_attr="active_assignees",
            ),
            Prefetch(
                "label_issue",
                queryset=IssueLabel.objects.filter(deleted_at__isnull=True, label__deleted_at__isnull=True)
                .select_related("label")
                .order_by("label__name"),
                to_attr="active_labels",
            ),
            Prefetch(
                "issue_module",
                # archived modules are hidden on work items, as in the app
                queryset=ModuleIssue.objects.filter(
                    deleted_at__isnull=True, module__deleted_at__isnull=True, module__archived_at__isnull=True
                ).select_related("module"),
                to_attr="active_modules",
            ),
            Prefetch(
                "issue_cycle",
                queryset=CycleIssue.objects.filter(
                    deleted_at__isnull=True, cycle__deleted_at__isnull=True
                ).select_related("cycle"),
                to_attr="active_cycles",
            ),
        )
    )


def _key(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"


def work_item_row(issue):
    """A work item as a row of the list (Work items screen): every column."""
    cycle = issue.active_cycles[0].cycle if getattr(issue, "active_cycles", None) else None
    return {
        "id": str(issue.id),
        "key": _key(issue),
        "sequence_id": issue.sequence_id,
        "name": issue.name,
        "type": type_brief(issue.type),
        "state": state_brief(issue.state),
        "priority": issue.priority or "none",
        "priority_label": PRIORITY_LABELS.get(issue.priority or "none", "None"),
        "assignees": [user_brief(item.assignee) for item in issue.active_assignees],
        "labels": [
            {"id": str(item.label.id), "name": item.label.name, "color": item.label.color}
            for item in issue.active_labels
        ],
        "modules": [{"id": str(item.module.id), "name": item.module.name} for item in issue.active_modules],
        "sprint": (
            {
                "id": str(cycle.id),
                "name": cycle.name,
                "start_date": iso(cycle.start_date),
                "end_date": iso(cycle.end_date),
            }
            if cycle
            else None
        ),
        "start_date": iso(issue.start_date),
        "due_date": iso(issue.target_date),
        "estimate": issue.estimate_point.value if issue.estimate_point_id and issue.estimate_point else None,
        "parent": (
            {"id": str(issue.parent.id), "key": _key(issue.parent), "name": issue.parent.name} if issue.parent else None
        ),
        "milestone": (
            {"id": str(issue.milestone.id), "code": issue.milestone.code, "name": issue.milestone.name}
            if issue.milestone
            else None
        ),
        "created_by": user_brief(issue.created_by),
        "updated_by": user_brief(issue.updated_by),
        "completed_at": iso(issue.completed_at),
        "created_at": iso(issue.created_at),
        "updated_at": iso(issue.updated_at),
    }


def _attachment(asset, storage):
    attributes = asset.attributes or {}
    return {
        "id": str(asset.id),
        "name": attributes.get("name") or asset.asset.name.rsplit("/", 1)[-1],
        "type": attributes.get("type"),
        "size": attributes.get("size") or asset.size,
        # a signed link to download it (valid for a limited time; ask the API again for a new one)
        "url": storage.generate_presigned_url(object_name=asset.asset.name, filename=attributes.get("name"))
        if storage
        else None,
        "uploaded_by": user_brief(asset.created_by),
        "created_at": iso(asset.created_at),
    }


def _comment(comment):
    return {
        "id": str(comment.id),
        "author": user_brief(comment.actor),
        "comment_html": comment.comment_html,
        "comment_text": comment.comment_stripped,
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
        "reactions": [
            {"reaction": item.reaction, "actor": user_brief(item.actor), "created_at": iso(item.created_at)}
            for item in getattr(comment, "active_reactions", [])
        ],
        "edited_at": iso(comment.edited_at),
        "created_at": iso(comment.created_at),
        "updated_at": iso(comment.updated_at),
    }


def _activity(activity):
    return {
        "id": str(activity.id),
        "actor": user_brief(activity.actor)
        or (
            {"id": None, "name": activity.external_actor_name, "display_name": None, "email": None, "avatar_url": None}
            if activity.external_actor_name
            else None
        ),
        "verb": activity.verb,
        "field": activity.field,
        "old_value": activity.old_value,
        "new_value": activity.new_value,
        "comment": activity.comment,
        "created_at": iso(activity.created_at),
    }


def _related(issue):
    return {"id": str(issue.id), "key": _key(issue), "name": issue.name, "state": state_brief(issue.state)}


def work_item_detail(issue, storage):
    """Everything the work item's screen shows: the row, its description, watchers, queue, custom fields, sub-work
    items, relations, links, attachments, reactions, comments and the history."""
    data = work_item_row(issue)
    data["project"] = project_brief(issue.project)
    data["description_html"] = issue.description_html or ""
    data["description_text"] = issue.description_stripped or ""
    data["archived_at"] = iso(issue.archived_at)

    data["watchers"] = [
        user_brief(item.subscriber)
        for item in IssueSubscriber.objects.filter(issue=issue, deleted_at__isnull=True).select_related("subscriber")
    ]
    data["queues"] = [
        {"id": str(item.group.id), "name": item.group.name, "color": item.group.color, "note": item.note}
        for item in QueueItem.objects.filter(issue=issue, deleted_at__isnull=True, group__deleted_at__isnull=True)
        .select_related("group")
        .order_by("group__name")
    ]
    values = list(
        CustomFieldValue.objects.filter(issue=issue, deleted_at__isnull=True, field__deleted_at__isnull=True)
        .select_related("field")
        .order_by("field__sort_order")
    )
    # a People field stores user ids: they are sent as people (one query for all of them)
    person_ids = {
        str(person_id)
        for item in values
        if item.field.field_type == "user"
        for person_id in (item.value if isinstance(item.value, list) else [item.value])
        if person_id and is_valid_uuid(str(person_id))
    }
    people = {str(user.id): user for user in User.objects.filter(pk__in=person_ids)} if person_ids else {}

    def field_value(item):
        if item.field.field_type != "user":
            return item.value
        ids = item.value if isinstance(item.value, list) else [item.value]
        return [user_brief(people[str(person_id)]) for person_id in ids if person_id and str(person_id) in people]

    data["custom_fields"] = [
        {
            "id": str(item.field.id),
            "name": item.field.name,
            "field_type": item.field.field_type,
            "value": field_value(item),
        }
        for item in values
    ]
    data["sub_work_items"] = [
        {
            **_related(child),
            "priority": child.priority or "none",
            # only the current assignees (a removed one stays in the table, marked deleted)
            "assignees": [user_brief(item.assignee) for item in child.active_assignees],
        }
        for child in Issue.issue_objects.filter(parent=issue)
        .select_related("project", "state")
        .prefetch_related(
            Prefetch(
                "issue_assignee",
                queryset=IssueAssignee.objects.filter(deleted_at__isnull=True).select_related("assignee"),
                to_attr="active_assignees",
            )
        )
        .order_by("sequence_id")
    ]
    relations = []
    for relation in IssueRelation.objects.filter(
        Q(issue=issue) | Q(related_issue=issue), deleted_at__isnull=True
    ).select_related(
        "issue", "issue__project", "issue__state", "related_issue", "related_issue__project", "related_issue__state"
    ):
        outgoing = relation.issue_id == issue.id
        other = relation.related_issue if outgoing else relation.issue
        if other.deleted_at:
            continue
        relations.append(
            {
                "id": str(relation.id),
                "relation_type": relation.relation_type,
                # "outgoing": this work item <relation_type> the other one; "incoming": the other way round
                "direction": "outgoing" if outgoing else "incoming",
                "work_item": _related(other),
            }
        )
    data["relations"] = relations
    data["links"] = [
        {
            "id": str(link.id),
            "title": link.title,
            "url": link.url,
            "created_by": user_brief(link.created_by),
            "created_at": iso(link.created_at),
        }
        for link in IssueLink.objects.filter(issue=issue, deleted_at__isnull=True)
        .select_related("created_by")
        .order_by("-created_at")
    ]
    data["attachments"] = [
        _attachment(asset, storage)
        for asset in FileAsset.objects.filter(
            issue_id=issue.id,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            is_uploaded=True,
            deleted_at__isnull=True,
        )
        .select_related("created_by")
        .order_by("-created_at")
    ]
    data["reactions"] = [
        {"reaction": item.reaction, "actor": user_brief(item.actor), "created_at": iso(item.created_at)}
        for item in IssueReaction.objects.filter(issue=issue, deleted_at__isnull=True).select_related("actor")
    ]
    data["comments"] = [
        _comment(comment)
        for comment in IssueComment.objects.filter(issue=issue, deleted_at__isnull=True)
        .select_related("actor")
        .prefetch_related(
            Prefetch(
                "comment_reactions",
                queryset=CommentReaction.objects.filter(deleted_at__isnull=True).select_related("actor"),
                to_attr="active_reactions",
            )
        )
        .order_by("created_at")
    ]
    data["activity"] = [
        _activity(activity)
        for activity in IssueActivity.objects.filter(issue=issue, deleted_at__isnull=True)
        # as the app's history: comments are under "comments"; votes, reactions and drafts are not shown there
        .exclude(field__in=["comment", "vote", "reaction", "draft"])
        .select_related("actor")
        .order_by("created_at")
    ]
    intake = IntakeIssue.objects.filter(issue=issue, deleted_at__isnull=True).select_related("created_by").first()
    data["intake"] = (
        {
            "status": INTAKE_STATUS.get(intake.status, str(intake.status)),
            "source_email": intake.source_email,
            "requested_by": user_brief(intake.created_by),
            "created_at": iso(intake.created_at),
        }
        if intake
        else None
    )
    return data
