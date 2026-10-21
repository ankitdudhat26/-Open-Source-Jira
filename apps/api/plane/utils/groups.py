# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Groups (e.g. DevOps) and their queues (Q).

* A workspace admin creates groups, picks their rights and adds any workspace member to them.
* A group with a queue receives work items from every project ("Send to queue").
* Members of the group see every work item of their queue, with the project, read only.
* They can take (self assign) a work item; once it is theirs they can change it (status, priority, dates)
  and comment. Taking a work item adds them to its project as a Client, so they also see it there.

Rights are keys in GROUP_PERMISSIONS; a new right is added here and can then be given to any group.
"""

import json

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from plane.db.models import (
    Issue,
    IssueActivity,
    IssueAssignee,
    ProjectMember,
    ProjectUserProperty,
    QueueItem,
    WorkspaceGroup,
    WorkspaceGroupMember,
    WorkspaceMember,
)

ADMIN_ROLE = 20
CLIENT_ROLE = 5
DONE_GROUPS = ("completed", "cancelled")

GROUP_PERMISSIONS = {
    "queue.view": {
        "label": "View the queue",
        "description": "See every work item sent to this group's queue, from all projects (read only).",
    },
    "queue.self_assign": {
        "label": "Self assign",
        "description": "Take work items from the queue by assigning them to themselves.",
    },
    "queue.edit_assigned": {
        "label": "Change assigned work items",
        "description": "Change the status, priority and dates of queue work items assigned to them, and comment.",
    },
}

DEFAULT_GROUPS = [
    {
        "name": "DevOps",
        "description": "Infrastructure, deployments and environment requests from every project.",
        "color": "#0EA5E9",
        "has_queue": True,
        "permissions": list(GROUP_PERMISSIONS),
    }
]


class GroupError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def ensure_default_groups(workspace):
    """Create the default groups (DevOps) of a workspace once."""
    if WorkspaceGroup.all_objects.filter(workspace=workspace, is_default=True).exists():
        return
    for index, config in enumerate(DEFAULT_GROUPS):
        try:
            with transaction.atomic():
                WorkspaceGroup.objects.get_or_create(
                    workspace=workspace,
                    name=config["name"],
                    defaults={
                        **{k: v for k, v in config.items() if k != "name"},
                        "is_default": True,
                        "sort_order": (index + 1) * 10000,
                    },
                )
        except IntegrityError:
            pass


def clean_permissions(permissions):
    if not isinstance(permissions, list):
        raise GroupError("permissions must be a list.")
    unknown = [permission for permission in permissions if permission not in GROUP_PERMISSIONS]
    if unknown:
        raise GroupError(f"Unknown rights: {', '.join(map(str, unknown))}.")
    # self assign / editing only make sense together with seeing the queue
    cleaned = list(dict.fromkeys(permissions))
    if cleaned and "queue.view" not in cleaned:
        cleaned.insert(0, "queue.view")
    return cleaned


def is_workspace_admin(workspace_id, user_id):
    return WorkspaceMember.objects.filter(
        workspace_id=workspace_id, member_id=user_id, is_active=True, role=ADMIN_ROLE
    ).exists()


def user_group_rights(group, user_id):
    """Rights the user has through the group (empty set when they are not a member)."""
    if not WorkspaceGroupMember.objects.filter(group=group, member_id=user_id).exists():
        return set()
    return set(group.permissions)


def can_view_queue(group, user_id):
    return group.has_queue and (
        "queue.view" in user_group_rights(group, user_id) or is_workspace_admin(group.workspace_id, user_id)
    )


def visible_queue_groups(workspace, user_id):
    """Queues the user can open: their groups with the view right (admins see every queue)."""
    groups = WorkspaceGroup.objects.filter(workspace=workspace, has_queue=True)
    if is_workspace_admin(workspace.id, user_id):
        return groups
    return groups.filter(
        group_members__member_id=user_id, group_members__deleted_at__isnull=True, permissions__contains=["queue.view"]
    ).distinct()


def queue_issues(group):
    """Work items of a queue (not deleted, archived or draft)."""
    return Issue.issue_objects.filter(queue_items__group=group, queue_items__deleted_at__isnull=True)


def queue_counts(group, user_id):
    issues = queue_issues(group)
    open_issues = issues.exclude(state__group__in=DONE_GROUPS)
    unassigned = open_issues.annotate(
        active_assignees=Count("issue_assignee", filter=Q(issue_assignee__deleted_at__isnull=True))
    ).filter(active_assignees=0)
    return {
        "open": open_issues.count(),
        "unassigned": unassigned.count(),
        "mine": open_issues.filter(issue_assignee__assignee_id=user_id, issue_assignee__deleted_at__isnull=True)
        .distinct()
        .count(),
        "done": issues.filter(state__group__in=DONE_GROUPS).count(),
    }


def is_assigned(issue, user_id):
    return IssueAssignee.objects.filter(issue=issue, assignee_id=user_id).exists()


def _log_activity(issue, actor_id, field, old_value, new_value, comment, old_identifier=None, new_identifier=None):
    IssueActivity.objects.create(
        issue=issue,
        project_id=issue.project_id,
        workspace_id=issue.workspace_id,
        actor_id=actor_id,
        verb="updated",
        field=field,
        old_value=old_value or "",
        new_value=new_value or "",
        old_identifier=old_identifier,
        new_identifier=new_identifier,
        comment=comment,
        epoch=int(timezone.now().timestamp()),
    )


def ensure_project_access(issue, user_id, group):
    """Make the user a member of the work item's project (Client, or Admin for workspace admins) if they are not."""
    membership = ProjectMember.objects.filter(project_id=issue.project_id, member_id=user_id).first()
    if membership and membership.is_active:
        return membership
    role = ADMIN_ROLE if is_workspace_admin(issue.workspace_id, user_id) else CLIENT_ROLE
    if membership:
        membership.is_active = True
        membership.role = role
        membership.designation = membership.designation or group.name
        membership.save(update_fields=["is_active", "role", "designation", "updated_at"])
    else:
        membership = ProjectMember.objects.create(
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            member_id=user_id,
            role=role,
            designation=group.name,
        )
    ProjectUserProperty.objects.get_or_create(
        project_id=issue.project_id, user_id=user_id, defaults={"workspace_id": issue.workspace_id}
    )
    return membership


def self_assign(group, issue, user_id, origin=None):
    from plane.bgtasks.issue_activities_task import issue_activity

    if "queue.self_assign" not in user_group_rights(group, user_id):
        raise GroupError("You cannot take work items from this queue.", 403)
    if issue.state and issue.state.group in DONE_GROUPS:
        raise GroupError("This work item is already done.")
    if is_assigned(issue, user_id):
        return
    current_ids = [str(i) for i in IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True)]
    with transaction.atomic():
        ensure_project_access(issue, user_id, group)
        IssueAssignee.objects.create(
            issue=issue, assignee_id=user_id, project_id=issue.project_id, workspace_id=issue.workspace_id
        )
    issue_activity.delay(
        type="issue.activity.updated",
        requested_data=json.dumps({"assignee_ids": [*current_ids, str(user_id)]}),
        actor_id=str(user_id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=json.dumps({"assignee_ids": current_ids}),
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=origin,
    )


def unassign_self(issue, user_id, origin=None):
    from plane.bgtasks.issue_activities_task import issue_activity

    current_ids = [str(i) for i in IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True)]
    if str(user_id) not in current_ids:
        return
    IssueAssignee.objects.filter(issue=issue, assignee_id=user_id).delete()
    issue_activity.delay(
        type="issue.activity.updated",
        requested_data=json.dumps({"assignee_ids": [i for i in current_ids if i != str(user_id)]}),
        actor_id=str(user_id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=json.dumps({"assignee_ids": current_ids}),
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=origin,
    )


def send_to_queue(issue, group, actor_id):
    """Put the work item in the group's queue (moving it out of another queue). None removes it from its queue."""
    current = QueueItem.objects.filter(issue=issue).select_related("group").first()
    if group is not None and not group.has_queue:
        raise GroupError("This group has no queue.")
    if group is not None and group.workspace_id != issue.workspace_id:
        raise GroupError("Unknown group.", 404)
    if (current.group_id if current else None) == (group.id if group else None):
        return current
    old_name = current.group.name if current else ""
    with transaction.atomic():
        if current:
            current.delete(soft=False)
        item = (
            QueueItem.objects.create(
                issue=issue,
                group=group,
                project_id=issue.project_id,
                workspace_id=issue.workspace_id,
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
            if group
            else None
        )
        _log_activity(
            issue,
            actor_id,
            "queue",
            old_name,
            group.name if group else "",
            f"sent the work item to the {group.name} queue" if group else "removed the work item from the queue",
            old_identifier=current.group_id if current else None,
            new_identifier=group.id if group else None,
        )
    return item


def serialize_queue_issue(issue, user_id, project_map=None):
    project = issue.project
    state = issue.state
    assignee_ids = [str(record.assignee_id) for record in issue.issue_assignee.all() if record.deleted_at is None]
    return {
        "id": str(issue.id),
        "name": issue.name,
        "sequence_id": issue.sequence_id,
        "key": f"{project.identifier}-{issue.sequence_id}",
        "project": {"id": str(project.id), "name": project.name, "identifier": project.identifier},
        "state": (
            {"id": str(state.id), "name": state.name, "group": state.group, "color": state.color} if state else None
        ),
        "priority": issue.priority,
        "type": issue.type.name if issue.type_id else None,
        "assignee_ids": assignee_ids,
        "is_mine": str(user_id) in assignee_ids,
        "start_date": issue.start_date,
        "target_date": issue.target_date,
        "created_at": issue.created_at,
        "created_by": str(issue.created_by_id) if issue.created_by_id else None,
    }
