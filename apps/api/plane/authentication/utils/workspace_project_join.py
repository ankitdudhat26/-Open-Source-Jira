# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db.models import Count, Q

# Module imports
from plane.db.models import (
    Profile,
    ProjectMember,
    ProjectMemberInvite,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberInvite,
)
from plane.utils.cache import invalidate_cache_directly

CLIENT = 5


def process_workspace_project_invitations(user):
    """This function takes in User and adds him to all workspace and projects that the user has accepted invited of"""

    # Check if user has any accepted invites for workspace and add them to workspace
    workspace_member_invites = WorkspaceMemberInvite.objects.filter(email=user.email, accepted=True)

    WorkspaceMember.objects.bulk_create(
        [
            WorkspaceMember(
                workspace_id=workspace_member_invite.workspace_id,
                member=user,
                role=workspace_member_invite.role,
                is_sub_admin=workspace_member_invite.is_sub_admin,
                company_role=workspace_member_invite.designation,
            )
            for workspace_member_invite in workspace_member_invites
        ],
        ignore_conflicts=True,
    )

    for workspace_member_invite in workspace_member_invites:
        invalidate_cache_directly(
            path=f"/api/workspaces/{str(workspace_member_invite.workspace.slug)}/members/",
            url_params=False,
            user=False,
            multiple=True,
        )

    # Check if user has any project invites
    project_member_invites = ProjectMemberInvite.objects.filter(email=user.email, accepted=True)

    # Add user to workspace
    WorkspaceMember.objects.bulk_create(
        [
            WorkspaceMember(
                workspace_id=project_member_invite.workspace_id,
                role=(project_member_invite.role if project_member_invite.role in [5, 15] else 15),
                member=user,
                created_by_id=project_member_invite.created_by_id,
            )
            for project_member_invite in project_member_invites
        ],
        ignore_conflicts=True,
    )

    # Now add the users to project
    ProjectMember.objects.bulk_create(
        [
            ProjectMember(
                workspace_id=project_member_invite.workspace_id,
                role=(project_member_invite.role if project_member_invite.role in [5, 15] else 15),
                member=user,
                created_by_id=project_member_invite.created_by_id,
            )
            for project_member_invite in project_member_invites
        ],
        ignore_conflicts=True,
    )

    # Delete all the invites
    workspace_member_invites.delete()
    project_member_invites.delete()


def default_workspace():
    """The organization's workspace: DEFAULT_WORKSPACE_SLUG, else the one most people are in (side workspaces made
    for testing are older or newer, but small)."""
    if settings.DEFAULT_WORKSPACE_SLUG:
        return Workspace.objects.filter(slug=settings.DEFAULT_WORKSPACE_SLUG).first()
    return (
        Workspace.objects.annotate(
            people=Count(
                "workspace_member",
                filter=Q(
                    workspace_member__is_active=True,
                    workspace_member__deleted_at__isnull=True,
                    workspace_member__member__is_bot=False,
                ),
            )
        )
        .order_by("-people", "created_at")
        .first()
    )


def join_default_workspace(user, workspace=None):
    """Someone who signed up with the app link (no invite) and belongs to no workspace joins the organization's
    workspace as a Client: admins see them in Members and give them their role. Otherwise onboarding has them create
    a workspace of their own. People removed from a workspace keep their (deactivated) membership, so never rejoin."""
    if user.is_bot or (workspace is None and WorkspaceMember.objects.filter(member=user).exists()):
        return None
    workspace = workspace or default_workspace()
    if workspace is None:
        return None
    membership, created = WorkspaceMember.objects.get_or_create(
        workspace=workspace, member=user, defaults={"role": CLIENT}
    )
    if created:
        Profile.objects.filter(user=user, last_workspace_id__isnull=True).update(last_workspace_id=workspace.id)
        invalidate_cache_directly(
            path=f"/api/workspaces/{workspace.slug}/members/", url_params=False, user=False, multiple=True
        )
    return membership if created else None
