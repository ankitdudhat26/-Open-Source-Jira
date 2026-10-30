# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bringing workspace members into a project, e.g. the member mapped to a resource (role) of the project."""

# Django imports
from django.db.models import Min

# Module imports
from plane.bgtasks.project_add_user_email_task import project_add_user_email
from plane.db.models import ProjectMember, ProjectUserProperty, WorkspaceMember

MEMBER = 15
ADMIN = 20
DEFAULT_DESIGNATION = "Developer"


def is_workspace_assignable(workspace_id, user_id):
    """Any active member of the workspace — admin, member or client — can be brought into its projects."""
    return WorkspaceMember.objects.filter(
        workspace_id=workspace_id, member_id=user_id, is_active=True, member__is_bot=False
    ).exists()


def is_project_client(user, slug, project_id):
    """A client of the project (its guest role) who is not a workspace admin: they only view its work items."""
    return (
        ProjectMember.objects.filter(
            project_id=project_id, workspace__slug=slug, member=user, is_active=True, role__lt=MEMBER
        ).exists()
        and not WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True, role=ADMIN).exists()
    )


def is_project_assignee_role(project_id, user_id):
    """Work items can be assigned to the members and admins of a project only (not to its clients)."""
    return ProjectMember.objects.filter(
        project_id=project_id, member_id=user_id, is_active=True, role__gte=MEMBER
    ).exists()


def add_members_to_project(project, user_ids, actor_id, origin, designation=""):
    """Add the given workspace members who are not in the project yet as project members and email them.

    Any active workspace member joins — admins, members and clients alike. Their project access level follows their
    workspace role, so a client joins as a client. Their project role is `designation` when given, else their job in
    the organisation, else the one they hold in their latest project, else "Developer". Returns the ids of the members
    added.
    """
    if not user_ids:
        return []

    workspace_members = list(
        WorkspaceMember.objects.filter(
            workspace_id=project.workspace_id,
            member_id__in=user_ids,
            is_active=True,
            member__is_bot=False,
        ).values_list("member_id", "role", "company_role")
    )
    workspace_roles = {member_id: role for member_id, role, _ in workspace_members}
    # in the project already, unless a workspace member/admin is only a client of it (they are brought up)
    in_project = {
        member_id
        for member_id, role in ProjectMember.objects.filter(
            project=project, member_id__in=workspace_roles.keys(), is_active=True
        ).values_list("member_id", "role")
        if role >= MEMBER or workspace_roles[member_id] < MEMBER
    }
    new_ids = [member_id for member_id in workspace_roles if member_id not in in_project]
    if not new_ids:
        return []

    designation = (designation or "").strip()[:255]
    designations = {}
    if designation:
        designations = dict.fromkeys(new_ids, designation)
    else:
        for member_id, _, job in workspace_members:
            if (job or "").strip():
                designations[member_id] = job.strip()[:255]
        for member_id, previous in (
            ProjectMember.objects.filter(workspace_id=project.workspace_id, member_id__in=new_ids)
            .exclude(designation="")
            .order_by("-updated_at")
            .values_list("member_id", "designation")
        ):
            designations.setdefault(member_id, previous)

    # a removed member (or a client) comes back with the access level of their workspace role
    existing = {
        project_member.member_id: project_member
        for project_member in ProjectMember.objects.filter(project=project, member_id__in=new_ids)
    }
    for member_id, project_member in existing.items():
        project_member.role = workspace_roles[member_id]
        project_member.is_active = True
        project_member.designation = (
            designation or project_member.designation or designations.get(member_id, DEFAULT_DESIGNATION)
        )
    ProjectMember.objects.bulk_update(existing.values(), ["role", "is_active", "designation"], batch_size=100)

    sort_orders = dict(
        ProjectUserProperty.objects.filter(workspace_id=project.workspace_id, user_id__in=new_ids)
        .values("user_id")
        .annotate(min_sort_order=Min("sort_order"))
        .values_list("user_id", "min_sort_order")
    )
    created_ids = [member_id for member_id in new_ids if member_id not in existing]
    ProjectMember.objects.bulk_create(
        [
            ProjectMember(
                project=project,
                workspace_id=project.workspace_id,
                member_id=member_id,
                role=workspace_roles[member_id],
                designation=designations.get(member_id, DEFAULT_DESIGNATION),
            )
            for member_id in created_ids
        ],
        batch_size=100,
        ignore_conflicts=True,
    )
    ProjectUserProperty.objects.bulk_create(
        [
            ProjectUserProperty(
                project=project,
                workspace_id=project.workspace_id,
                user_id=member_id,
                sort_order=(sort_orders[member_id] - 10000 if sort_orders.get(member_id) is not None else 65535),
            )
            for member_id in created_ids
        ],
        batch_size=100,
        ignore_conflicts=True,
    )

    for project_member_id in ProjectMember.objects.filter(
        project=project, member_id__in=new_ids, is_active=True
    ).values_list("id", flat=True):
        project_add_user_email.delay(origin, project_member_id, actor_id)
    return new_ids
