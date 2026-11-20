# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""People who signed up with the app link before sign up was invitation only: the command adds them to the
organization's workspace (the one most people are in) as Clients, so they show in Members."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command

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
class TestAddSignupsToWorkspace:
    @pytest.mark.django_db
    def test_command_adds_earlier_signups(self, workspace, newer_workspace, team):
        stuck = _user("stuck@acme.com")
        own = _user("own@acme.com")
        WorkspaceMember.objects.create(workspace=newer_workspace, member=own, role=20)

        listed = StringIO()
        call_command("add_signups_to_workspace", stdout=listed)
        assert "stuck@acme.com" in listed.getvalue() and "own@acme.com" in listed.getvalue()
        assert not WorkspaceMember.objects.filter(member=stuck).exists()  # only listed

        # an older workspace with one person is not the organization's
        old = Workspace.objects.create(name="Test", owner=own, slug="old-test")
        Workspace.objects.filter(pk=old.pk).update(created_at=workspace.created_at.replace(year=2020))

        call_command("add_signups_to_workspace", "--apply", stdout=StringIO())
        assert WorkspaceMember.objects.get(member=stuck).workspace_id == workspace.id
        assert WorkspaceMember.objects.filter(member=own, workspace=workspace, role=5).exists()
        # still in their own workspace too
        assert WorkspaceMember.objects.filter(member=own, workspace=newer_workspace, role=20).exists()
