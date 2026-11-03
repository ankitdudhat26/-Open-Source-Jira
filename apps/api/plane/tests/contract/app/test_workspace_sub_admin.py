# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Sub Admin: a workspace Member who can also create projects (with full access to them) and invite people as Member
or Client. Plain Members no longer create projects; a Sub Admin only sees the projects they are in."""

import uuid
from unittest import mock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Project, ProjectMember, User, WorkspaceMember, WorkspaceMemberInvite


def _person(workspace, role=15, is_sub_admin=False):
    user = User.objects.create(email=f"{uuid.uuid4().hex[:10]}@example.com", username=uuid.uuid4().hex)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_sub_admin=is_sub_admin)
    api = APIClient()
    api.force_authenticate(user=user)
    return user, api


def _projects_url(workspace):
    return f"/api/workspaces/{workspace.slug}/projects/"


def _invite(api, workspace, **invitee):
    with mock.patch("plane.app.views.workspace.invite.workspace_invitation.delay") as send:
        response = api.post(
            f"/api/workspaces/{workspace.slug}/invitations/",
            {"emails": [{"email": "new-person@example.com", "role": 15, "designation": "Developer", **invitee}]},
            format="json",
        )
    return response, send


@pytest.mark.contract
class TestWorkspaceSubAdmin:
    @pytest.mark.django_db
    def test_member_cannot_create_a_project(self, workspace):
        _, member_api = _person(workspace)

        response = member_api.post(_projects_url(workspace), {"name": "Side Project", "identifier": "SIDE"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Project.objects.filter(identifier="SIDE").exists()

    @pytest.mark.django_db
    def test_sub_admin_creates_a_project_and_gets_full_access(self, workspace):
        sub_admin, api = _person(workspace, is_sub_admin=True)

        response = api.post(_projects_url(workspace), {"name": "Client Portal", "identifier": "CPORT"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        project = Project.objects.get(identifier="CPORT")
        assert ProjectMember.objects.get(project=project, member=sub_admin).role == 20

    @pytest.mark.django_db
    def test_sub_admin_invites_members_and_clients_only(self, workspace):
        _, api = _person(workspace, is_sub_admin=True)

        as_member, sent = _invite(api, workspace)
        as_admin, _ = _invite(api, workspace, email="boss@example.com", role=20)
        as_sub_admin, _ = _invite(api, workspace, email="peer@example.com", is_sub_admin=True)

        assert as_member.status_code == status.HTTP_200_OK, as_member.data
        sent.assert_called_once()
        assert as_admin.status_code == status.HTTP_400_BAD_REQUEST
        assert as_sub_admin.status_code == status.HTTP_400_BAD_REQUEST
        assert list(WorkspaceMemberInvite.objects.values_list("email", flat=True)) == ["new-person@example.com"]

    @pytest.mark.django_db
    def test_member_cannot_invite(self, workspace):
        _, member_api = _person(workspace)

        response, sent = _invite(member_api, workspace)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        sent.assert_not_called()

    @pytest.mark.django_db
    def test_admin_invites_a_sub_admin_who_joins_as_one(self, session_client, workspace):
        response, _ = _invite(session_client, workspace, is_sub_admin=True)
        invite = WorkspaceMemberInvite.objects.get(email="new-person@example.com")
        user = User.objects.create(email="new-person@example.com", username=uuid.uuid4().hex)
        api = APIClient()
        api.force_authenticate(user=user)

        joined = api.post("/api/users/me/workspaces/invitations/", {"invitations": [str(invite.id)]}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert joined.status_code == status.HTTP_204_NO_CONTENT
        membership = WorkspaceMember.objects.get(workspace=workspace, member=user)
        assert (membership.role, membership.is_sub_admin) == (15, True)

    @pytest.mark.django_db
    def test_admin_makes_a_member_sub_admin_and_another_role_drops_it(self, session_client, workspace):
        user, _ = _person(workspace)
        membership = WorkspaceMember.objects.get(workspace=workspace, member=user)
        url = f"/api/workspaces/{workspace.slug}/members/{membership.id}/"

        session_client.patch(url, {"is_sub_admin": True}, format="json")
        membership.refresh_from_db()
        assert (membership.role, membership.is_sub_admin) == (15, True)

        session_client.patch(url, {"role": 20}, format="json")
        membership.refresh_from_db()
        assert (membership.role, membership.is_sub_admin) == (20, False)

    @pytest.mark.django_db
    def test_sub_admin_only_lists_projects_they_are_in(self, workspace, create_user):
        public = Project.objects.create(name="Public", identifier="PUB", workspace=workspace, network=2)
        ProjectMember.objects.create(project=public, member=create_user, workspace=workspace, role=20)
        mine = Project.objects.create(name="Mine", identifier="MINE", workspace=workspace, network=2)
        sub_admin, sub_admin_api = _person(workspace, is_sub_admin=True)
        ProjectMember.objects.create(project=mine, member=sub_admin, workspace=workspace, role=20)
        _, member_api = _person(workspace)

        sub_admin_sees = {p["identifier"] for p in sub_admin_api.get(_projects_url(workspace)).data}
        member_sees = {p["identifier"] for p in member_api.get(_projects_url(workspace)).data}

        assert sub_admin_sees == {"MINE"}
        assert {"PUB", "MINE"} <= member_sees
