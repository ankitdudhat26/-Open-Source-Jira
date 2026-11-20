# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Link an account someone made by signing up with the app link to the member they already are (an account the
Jira import made, with all their work items, comments and history): the member's account takes over the sign in."""

# Django imports
from django.db import transaction

# Module imports
from plane.db.models import Account, JiraEntityMap, Profile, ProjectMember, Session, User, Workspace, WorkspaceMember
from plane.license.models import InstanceAdmin

# what makes the sign in: the password and how and when it was last used
SIGN_IN_FIELDS = (
    "password",
    "is_password_autoset",
    "last_login",
    "last_login_time",
    "last_login_ip",
    "last_login_medium",
    "last_login_uagent",
    "last_active",
)


def merge_refusal(other, actor):
    """Why the account cannot be merged into another one (by `actor`), or None."""
    if other.pk == actor.pk:
        return "it is your own account"
    if other.is_bot:
        return "it is a bot"
    if InstanceAdmin.objects.filter(user=other).exists():
        return "it is an instance admin"
    return None


def merge_signed_up_account(user, other, workspace):
    """The member `user` (never signed in to) takes over the sign in of `other` (email, password, social logins) and
    `other`'s workspaces and projects; `other` is switched off. Its sessions end: the person signs in again with the
    same email and password and is the member, with their history."""
    with transaction.atomic():
        email = other.email
        sign_in = {field: getattr(other, field) for field in SIGN_IN_FIELDS}
        other.email = None
        other.is_active = False
        other.set_unusable_password()
        other.save(update_fields=["email", "is_active", "password", "updated_at"])

        for field, value in sign_in.items():
            setattr(user, field, value)
        user.email = email
        user.is_active = True
        user.is_email_verified = True
        if not user.avatar and not user.avatar_asset_id and (other.avatar or other.avatar_asset_id):
            user.avatar, user.avatar_asset_id = other.avatar, other.avatar_asset_id
        user.save()

        Account.objects.filter(user=other).update(user=user)
        # their other workspaces and projects (e.g. the one onboarding had them create) come along
        for membership in WorkspaceMember.objects.filter(member=other):
            if WorkspaceMember.objects.filter(member=user, workspace_id=membership.workspace_id).exists():
                membership.is_active = False
                membership.save(update_fields=["is_active", "updated_at"])
            else:
                membership.member = user
                membership.save(update_fields=["member", "updated_at"])
        for membership in ProjectMember.objects.filter(member=other):
            if ProjectMember.objects.filter(member=user, project_id=membership.project_id).exists():
                membership.is_active = False
                membership.save(update_fields=["is_active", "updated_at"])
            else:
                membership.member = user
                membership.save(update_fields=["member", "updated_at"])
        Workspace.objects.filter(owner=other).update(owner=user)

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_onboarded = True
        profile.last_workspace_id = workspace.id
        profile.onboarding_step = {
            "profile_complete": True,
            "workspace_create": True,
            "workspace_join": True,
            "workspace_invite": True,
        }
        profile.save(update_fields=["is_onboarded", "last_workspace_id", "onboarding_step", "updated_at"])

        Session.objects.filter(user_id=str(other.id)).delete()
        # the Jira user sync finds the person by this email, and keeps the account on
        JiraEntityMap.objects.filter(workspace=workspace, entity_type="user", plane_id=user.id).update(jira_key=email)
        JiraEntityMap.objects.filter(
            workspace=workspace, entity_type="user", plane_id=user.id, jira_updated="former"
        ).update(jira_updated="invited")
    return User.objects.get(pk=user.pk)
