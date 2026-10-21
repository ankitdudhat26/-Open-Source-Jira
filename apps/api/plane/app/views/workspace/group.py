# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Groups (e.g. DevOps), their queues (Q) and sending work items to a queue."""

# Python imports
import json

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import escape

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueCommentSerializer, IssueCreateSerializer
from plane.app.views.base import BaseAPIView
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    Issue,
    IssueComment,
    QueueItem,
    State,
    Workspace,
    WorkspaceGroup,
    WorkspaceGroupMember,
    WorkspaceMember,
)
from plane.utils.groups import (
    DONE_GROUPS,
    GROUP_PERMISSIONS,
    GroupError,
    can_view_queue,
    clean_permissions,
    ensure_default_groups,
    is_assigned,
    queue_counts,
    queue_issues,
    self_assign,
    send_to_queue,
    serialize_queue_issue,
    unassign_self,
    user_group_rights,
    visible_queue_groups,
)
from plane.utils.host import base_host
from plane.utils.uuid import is_valid_uuid
from plane.utils.work_item_automation import run_work_item_automation
from plane.utils.workflow import check_transition

EDITABLE_FIELDS = ("state_id", "priority", "start_date", "target_date")


def serialize_group(group):
    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "color": group.color,
        "has_queue": group.has_queue,
        "permissions": list(group.permissions),
        "is_default": group.is_default,
        "member_ids": [str(member_id) for member_id in group.group_members.all().values_list("member_id", flat=True)],
    }


def error_response(error):
    return Response({"error": str(error)}, status=getattr(error, "status_code", status.HTTP_400_BAD_REQUEST))


def set_group_members(group, member_ids, actor_id):
    if not isinstance(member_ids, list) or not all(is_valid_uuid(str(member_id)) for member_id in member_ids):
        raise GroupError("member_ids must be a list of user ids.")
    member_ids = {str(member_id) for member_id in member_ids}
    workspace_member_ids = {
        str(member_id)
        for member_id in WorkspaceMember.objects.filter(
            workspace_id=group.workspace_id, member_id__in=member_ids, is_active=True
        ).values_list("member_id", flat=True)
    }
    if member_ids - workspace_member_ids:
        raise GroupError("Only active workspace members can be added to a group.")
    current = {str(member_id) for member_id in group.group_members.values_list("member_id", flat=True)}
    WorkspaceGroupMember.objects.filter(group=group, member_id__in=current - member_ids).delete(soft=False)
    WorkspaceGroupMember.objects.bulk_create(
        [
            WorkspaceGroupMember(
                group=group,
                workspace_id=group.workspace_id,
                member_id=member_id,
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
            for member_id in member_ids - current
        ],
        ignore_conflicts=True,
    )


def apply_group_fields(group, data, actor_id):
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise GroupError("Group name is required.")
        group.name = name[:255]
    if "description" in data:
        group.description = str(data.get("description") or "")
    if "color" in data:
        group.color = str(data.get("color") or "")[:32]
    if "has_queue" in data:
        group.has_queue = bool(data.get("has_queue"))
    if "permissions" in data:
        group.permissions = clean_permissions(data.get("permissions"))
    group.updated_by_id = actor_id


class WorkspaceGroupEndpoint(BaseAPIView):
    """Every member can see the groups (to know who is in DevOps); only workspace admins change them."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        ensure_default_groups(workspace)
        groups = WorkspaceGroup.objects.filter(workspace=workspace).prefetch_related("group_members")
        return Response(
            {
                "groups": [serialize_group(group) for group in groups],
                "permissions": [{"key": key, **value} for key, value in GROUP_PERMISSIONS.items()],
            },
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        group = WorkspaceGroup(workspace=workspace, created_by=request.user, permissions=list(GROUP_PERMISSIONS))
        try:
            apply_group_fields(group, {"name": "", **request.data}, request.user.id)
            with transaction.atomic():
                group.save()
                if "member_ids" in request.data:
                    set_group_members(group, request.data.get("member_ids"), request.user.id)
        except GroupError as error:
            return error_response(error)
        except IntegrityError:
            return Response({"error": "A group with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serialize_group(group), status=status.HTTP_201_CREATED)


class WorkspaceGroupDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, group_id):
        group = WorkspaceGroup.objects.filter(workspace__slug=slug, pk=group_id).first()
        if group is None:
            return Response({"error": "Group not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            apply_group_fields(group, request.data, request.user.id)
            with transaction.atomic():
                group.save()
                if "member_ids" in request.data:
                    set_group_members(group, request.data.get("member_ids"), request.user.id)
        except GroupError as error:
            return error_response(error)
        except IntegrityError:
            return Response({"error": "A group with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serialize_group(group), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, group_id):
        group = WorkspaceGroup.objects.filter(workspace__slug=slug, pk=group_id).first()
        if group is None:
            return Response({"error": "Group not found."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            QueueItem.objects.filter(group=group).delete(soft=False)
            WorkspaceGroupMember.objects.filter(group=group).delete(soft=False)
            group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class QueueListEndpoint(BaseAPIView):
    """The queues the user can open, with their counts (open / unassigned / mine / done)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        ensure_default_groups(workspace)
        queues = []
        for group in visible_queue_groups(workspace, request.user.id):
            rights = user_group_rights(group, request.user.id)
            queues.append(
                {
                    "group": {"id": str(group.id), "name": group.name, "color": group.color},
                    "counts": queue_counts(group, request.user.id),
                    "is_member": bool(rights),
                    "can_self_assign": "queue.self_assign" in rights,
                    "can_edit_assigned": "queue.edit_assigned" in rights,
                }
            )
        return Response(queues, status=status.HTTP_200_OK)


def get_queue_group(slug, group_id, user_id):
    group = WorkspaceGroup.objects.filter(workspace__slug=slug, pk=group_id, has_queue=True).first()
    if group is None:
        raise GroupError("Queue not found.", 404)
    if not can_view_queue(group, user_id):
        raise GroupError("You do not have access to this queue.", 403)
    return group


def get_queue_issue(group, issue_id):
    issue = queue_issues(group).filter(pk=issue_id).select_related("project", "state", "type").first()
    if issue is None:
        raise GroupError("This work item is not in the queue.", 404)
    return issue


class QueueItemsEndpoint(BaseAPIView):
    FILTERS = ("unassigned", "mine", "open", "done", "all")

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, group_id):
        try:
            group = get_queue_group(slug, group_id, request.user.id)
        except GroupError as error:
            return error_response(error)
        view = request.query_params.get("filter", "open")
        issues = queue_issues(group).select_related("project", "state", "type").prefetch_related("issue_assignee")
        if view in ("unassigned", "mine", "open"):
            issues = issues.exclude(state__group__in=DONE_GROUPS)
        if view == "unassigned":
            issues = issues.annotate(
                active_assignees=Count("issue_assignee", filter=Q(issue_assignee__deleted_at__isnull=True))
            ).filter(active_assignees=0)
        elif view == "mine":
            issues = issues.filter(issue_assignee__assignee_id=request.user.id, issue_assignee__deleted_at__isnull=True)
        elif view == "done":
            issues = issues.filter(state__group__in=DONE_GROUPS)
        issues = issues.distinct().order_by("created_at")
        return Response(
            [serialize_queue_issue(issue, request.user.id) for issue in issues[:500]], status=status.HTTP_200_OK
        )


class QueueItemDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug, group_id, issue_id):
        try:
            group = get_queue_group(slug, group_id, request.user.id)
            issue = get_queue_issue(group, issue_id)
        except GroupError as error:
            return error_response(error)
        rights = user_group_rights(group, request.user.id)
        mine = is_assigned(issue, request.user.id)
        can_edit = mine and "queue.edit_assigned" in rights
        comments = IssueComment.objects.filter(issue=issue).select_related("actor").order_by("-created_at")[:50]
        data = serialize_queue_issue(issue, request.user.id)
        data.update(
            {
                "description": issue.description_stripped or "",
                "labels": list(issue.labels.values_list("name", flat=True)),
                "parent": (
                    {"key": f"{issue.project.identifier}-{issue.parent.sequence_id}", "name": issue.parent.name}
                    if issue.parent_id
                    else None
                ),
                "can_self_assign": "queue.self_assign" in rights and not mine,
                "can_edit": can_edit,
                "can_comment": can_edit,
                "states": (
                    [
                        {"id": str(state.id), "name": state.name, "group": state.group, "color": state.color}
                        for state in State.objects.filter(project_id=issue.project_id).order_by("sequence")
                    ]
                    if can_edit
                    else []
                ),
                "comments": [
                    {
                        "id": str(comment.id),
                        "actor": comment.actor.display_name if comment.actor else "",
                        "comment": comment.comment_stripped or "",
                        "created_at": comment.created_at,
                    }
                    for comment in reversed(list(comments))
                ],
            }
        )
        return Response(data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def patch(self, request, slug, group_id, issue_id):
        """Change a work item of the queue: only by its assignee, with the "change assigned work items" right."""
        try:
            group = get_queue_group(slug, group_id, request.user.id)
            issue = get_queue_issue(group, issue_id)
        except GroupError as error:
            return error_response(error)
        if not (
            is_assigned(issue, request.user.id) and "queue.edit_assigned" in user_group_rights(group, request.user.id)
        ):
            return Response(
                {"error": "Assign the work item to yourself before changing it."}, status=status.HTTP_403_FORBIDDEN
            )
        data = {key: request.data[key] for key in EDITABLE_FIELDS if key in request.data}
        if not data:
            return Response({"error": "Nothing to change."}, status=status.HTTP_400_BAD_REQUEST)
        if "state_id" in data:
            if not State.objects.filter(pk=data["state_id"], project_id=issue.project_id).exists():
                return Response({"error": "Unknown state."}, status=status.HTTP_400_BAD_REQUEST)
            workflow_error = check_transition(issue.project_id, issue.state_id, data["state_id"], request.user.id)
            if workflow_error:
                return Response(
                    {"error": workflow_error, "code": "WORKFLOW_TRANSITION_NOT_ALLOWED"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        current_instance = json.dumps(
            {
                "state_id": str(issue.state_id) if issue.state_id else None,
                "priority": issue.priority,
                "start_date": issue.start_date,
                "target_date": issue.target_date,
            },
            cls=DjangoJSONEncoder,
        )
        serializer = IssueCreateSerializer(issue, data=data, partial=True, context={"project_id": issue.project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        origin = base_host(request=request, is_app=True)
        run_work_item_automation(issue.id, request.user.id, origin=origin, state_changed="state_id" in data)
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps(data, cls=DjangoJSONEncoder),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=current_instance,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=origin,
        )
        issue = get_queue_issue(group, issue_id)
        return Response(serialize_queue_issue(issue, request.user.id), status=status.HTTP_200_OK)


class QueueItemAssignEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def post(self, request, slug, group_id, issue_id):
        try:
            group = get_queue_group(slug, group_id, request.user.id)
            issue = get_queue_issue(group, issue_id)
            self_assign(group, issue, request.user.id, origin=base_host(request=request, is_app=True))
        except GroupError as error:
            return error_response(error)
        return Response(serialize_queue_issue(get_queue_issue(group, issue_id), request.user.id), status=200)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def delete(self, request, slug, group_id, issue_id):
        try:
            group = get_queue_group(slug, group_id, request.user.id)
            issue = get_queue_issue(group, issue_id)
        except GroupError as error:
            return error_response(error)
        unassign_self(issue, request.user.id, origin=base_host(request=request, is_app=True))
        return Response(serialize_queue_issue(get_queue_issue(group, issue_id), request.user.id), status=200)


class QueueItemCommentEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def post(self, request, slug, group_id, issue_id):
        try:
            group = get_queue_group(slug, group_id, request.user.id)
            issue = get_queue_issue(group, issue_id)
        except GroupError as error:
            return error_response(error)
        if not (
            is_assigned(issue, request.user.id) and "queue.edit_assigned" in user_group_rights(group, request.user.id)
        ):
            return Response(
                {"error": "Assign the work item to yourself before commenting."}, status=status.HTTP_403_FORBIDDEN
            )
        text = str(request.data.get("comment") or "").strip()
        if not text:
            return Response({"error": "Comment is empty."}, status=status.HTTP_400_BAD_REQUEST)
        html = "".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip())
        comment = IssueComment.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=request.user,
            comment_html=html,
        )
        issue_activity.delay(
            type="comment.activity.created",
            requested_data=json.dumps(IssueCommentSerializer(comment).data, cls=DjangoJSONEncoder),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=base_host(request=request, is_app=True),
        )
        return Response(
            {
                "id": str(comment.id),
                "actor": request.user.display_name,
                "comment": comment.comment_stripped or text,
                "created_at": comment.created_at,
            },
            status=status.HTTP_201_CREATED,
        )


class WorkItemQueueEndpoint(BaseAPIView):
    """Which queue a work item is in; project admins and members send it to a queue or take it out."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        item = QueueItem.objects.filter(issue_id=issue_id, project_id=project_id).select_related("group").first()
        return Response(
            {"group_id": str(item.group_id) if item else None, "group_name": item.group.name if item else None},
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        issue = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
        if issue is None:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        group_id = request.data.get("group_id")
        group = None
        if group_id:
            if not is_valid_uuid(str(group_id)):
                return Response({"error": "Unknown group."}, status=status.HTTP_400_BAD_REQUEST)
            group = WorkspaceGroup.objects.filter(workspace__slug=slug, pk=group_id).first()
            if group is None:
                return Response({"error": "Unknown group."}, status=status.HTTP_404_NOT_FOUND)
        try:
            send_to_queue(issue, group, request.user.id)
        except GroupError as error:
            return error_response(error)
        return Response(
            {"group_id": str(group.id) if group else None, "group_name": group.name if group else None},
            status=status.HTTP_200_OK,
        )
