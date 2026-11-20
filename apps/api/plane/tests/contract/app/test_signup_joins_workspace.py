# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""People who sign up with the app link (no invite) join the organization's workspace and show in Members."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command

from plane.authentication.utils.user_auth_workflow import post_user_auth_workflow
from plane.db.models import Profile, User, Workspace, WorkspaceMember


def _user(email, **fields):
    user = User.objects.create(email=email, username=uuid.uuid4().hex, display_name=email.split("@")[0], **fields)
    Profile.objects.create(user=user)
    return user


@pytest.fixture
def newer_workspace(create_user, workspace):
    return Workspace.objects.create(name="Side", owner=create_user, slug="side-workspace")


@pytest.fixture
def team(workspace):
    """A few more people in the organization's workspace."""
    for index in range(2):
        WorkspaceMember.objects.create(workspace=workspace, member=_user(f"teammate{index}@acme.com"), role=15)


@pytest.mark.contract
class TestSignupJoinsWorkspace:
    @pytest.mark.django_db
    def test_signup_without_invite_joins_the_workspace_most_people_are_in_as_client(
        self, session_client, create_user, workspace, team
    ):
        # an older test workspace with one person is not the organization's
        old = Workspace.objects.create(name="Test", owner=create_user, slug="old-test")
        Workspace.objects.filter(pk=old.pk).update(created_at=workspace.created_at.replace(year=2020))
        WorkspaceMember.objects.create(workspace=old, member=_user("tester@acme.com"), role=20)
        user = _user("new.person@acme.com")

        post_user_auth_workflow(user, True, None)

        membership = WorkspaceMember.objects.get(member=user)
        assert (membership.workspace_id, membership.role, membership.is_active) == (workspace.id, 5, True)
        # onboarding sees a workspace and finishes there instead of asking to create one
        assert Profile.objects.get(user=user).last_workspace_id == workspace.id
        listed = session_client.get(f"/api/workspaces/{workspace.slug}/members/").data
        assert "new.person@acme.com" in [row["member"]["email"] for row in listed]

    @pytest.mark.django_db
    def test_the_configured_workspace_is_joined(self, workspace, newer_workspace, settings):
        settings.DEFAULT_WORKSPACE_SLUG = newer_workspace.slug
        user = _user("new.person@acme.com")

        post_user_auth_workflow(user, True, None)

        assert WorkspaceMember.objects.get(member=user).workspace_id == newer_workspace.id

    @pytest.mark.django_db
    def test_members_and_removed_members_are_left_as_they_are(self, workspace, newer_workspace):
        member = _user("member@acme.com")
        WorkspaceMember.objects.create(workspace=newer_workspace, member=member, role=15)
        removed = _user("removed@acme.com")
        WorkspaceMember.objects.create(workspace=workspace, member=removed, role=15, is_active=False)

        post_user_auth_workflow(member, False, None)
        post_user_auth_workflow(removed, False, None)

        assert list(WorkspaceMember.objects.filter(member=member).values_list("workspace_id", flat=True)) == [
            newer_workspace.id
        ]
        assert not WorkspaceMember.objects.get(member=removed).is_active

    @pytest.mark.django_db
    def test_command_adds_earlier_signups(self, workspace, newer_workspace, team):
        stuck = _user("stuck@acme.com")
        own = _user("own@acme.com")
        WorkspaceMember.objects.create(workspace=newer_workspace, member=own, role=20)

        listed = StringIO()
        call_command("add_signups_to_workspace", stdout=listed)
        assert "stuck@acme.com" in listed.getvalue() and "own@acme.com" in listed.getvalue()
        assert not WorkspaceMember.objects.filter(member=stuck).exists()  # only listed

        call_command("add_signups_to_workspace", "--apply", stdout=StringIO())
        assert WorkspaceMember.objects.get(member=stuck).workspace_id == workspace.id
        assert WorkspaceMember.objects.filter(member=own, workspace=workspace, role=5).exists()
        # still in their own workspace too
        assert WorkspaceMember.objects.filter(member=own, workspace=newer_workspace, role=20).exists()
