# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Admin / Member / Client access levels and the compulsory project role (job) of each member."""

import uuid
from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueComment,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
    WorkspaceMemberInvite,
)

ADMIN, MEMBER, CLIENT = 20, 15, 5


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Roles", "identifier": "ROLE"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def workspace_user(workspace, role=MEMBER):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(email=f"user-{suffix}@example.com", username=f"user_{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


def members_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/members/"


@pytest.mark.contract
class TestProjectRoleIsRequired:
    @pytest.mark.django_db
    @mock.patch("plane.app.views.project.member.project_add_user_email.delay")
    def test_member_is_added_with_access_level_and_project_role(self, _email, session_client, workspace, project):
        designer = workspace_user(workspace)

        response = session_client.post(
            members_url(workspace, project),
            {"members": [{"member_id": str(designer.id), "role": MEMBER, "designation": " Graphic Designer "}]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        member = ProjectMember.objects.get(project=project, member=designer)
        assert member.role == MEMBER
        assert member.designation == "Graphic Designer"
        listed = session_client.get(members_url(workspace, project)).data
        assert {"member": designer.id, "designation": "Graphic Designer"}.items() <= next(
            row for row in listed if row["member"] == designer.id
        ).items()

    @pytest.mark.django_db
    def test_member_without_project_role_is_rejected(self, session_client, workspace, project):
        developer = workspace_user(workspace)

        response = session_client.post(
            members_url(workspace, project),
            {"members": [{"member_id": str(developer.id), "role": MEMBER, "designation": "  "}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Project role is required" in response.data["error"]
        assert not ProjectMember.objects.filter(project=project, member=developer).exists()

    @pytest.mark.django_db
    def test_only_admins_change_project_roles(self, session_client, api_client, workspace, project):
        developer = workspace_user(workspace)
        member = ProjectMember.objects.create(
            project=project, workspace=workspace, member=developer, role=MEMBER, designation="Developer"
        )
        url = f"{members_url(workspace, project)}{member.id}/"

        # the project admin can change it
        response = session_client.patch(url, {"designation": "QA Engineer"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        member.refresh_from_db()
        assert member.designation == "QA Engineer"
        # but not to empty
        assert session_client.patch(url, {"designation": ""}, format="json").status_code == 400

        # a member cannot change someone else's project role
        other = workspace_user(workspace)
        ProjectMember.objects.create(project=project, workspace=workspace, member=other, role=MEMBER, designation="Dev")
        api_client.force_authenticate(user=other)
        assert api_client.patch(url, {"designation": "Lead"}, format="json").status_code == 403


@pytest.mark.contract
class TestClientAccess:
    @pytest.fixture
    def client_user(self, workspace, project):
        user = workspace_user(workspace, role=CLIENT)
        ProjectMember.objects.create(
            project=project, workspace=workspace, member=user, role=CLIENT, designation="Client"
        )
        return user

    @pytest.mark.django_db
    def test_new_projects_let_clients_see_all_work_items(self, project):
        assert project.guest_view_all_features is True

    @pytest.mark.django_db
    def test_client_sees_work_items_and_comments_but_cannot_edit_others(
        self, api_client, session_client, workspace, project, client_user
    ):
        issue = Issue.objects.create(name="Home page", project=project, workspace=workspace)
        base = f"/api/workspaces/{workspace.slug}/projects/{project.id}"
        api_client.force_authenticate(user=client_user)

        # sees the work item made by the team
        response = api_client.get(f"{base}/issues/{issue.id}/")
        assert response.status_code == status.HTTP_200_OK

        # can comment
        response = api_client.post(
            f"{base}/issues/{issue.id}/comments/", {"comment_html": "<p>Looks good</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert IssueComment.objects.filter(issue=issue, actor=client_user).exists()

        # cannot edit the work items of the team, but can create their own (see test_client_work_item_access_app)
        response = api_client.patch(f"{base}/issues/{issue.id}/", {"name": "Changed"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        response = api_client.post(f"{base}/issues/", {"name": "New"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        issue.refresh_from_db()
        assert issue.name == "Home page"

    @pytest.mark.django_db
    def test_client_cannot_get_an_editing_role_in_projects(self, session_client, workspace, project):
        client = workspace_user(workspace, role=CLIENT)

        response = session_client.post(
            members_url(workspace, project),
            {"members": [{"member_id": str(client.id), "role": MEMBER, "designation": "Client"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
class TestInvitationRole:
    @pytest.mark.django_db
    @mock.patch("plane.app.views.workspace.invite.workspace_invitation.delay")
    def test_invite_needs_a_role_and_it_becomes_the_members_default(
        self, _email, session_client, api_client, workspace
    ):
        url = f"/api/workspaces/{workspace.slug}/invitations/"

        response = session_client.post(
            url, {"emails": [{"email": "designer@example.com", "role": MEMBER}]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Role is required" in response.data["error"]

        response = session_client.post(
            url,
            {"emails": [{"email": "designer@example.com", "role": MEMBER, "designation": "Graphic Designer"}]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        invite = WorkspaceMemberInvite.objects.get(email="designer@example.com")
        assert invite.designation == "Graphic Designer"

        designer = User.objects.create(email="designer@example.com", username="designer")
        api_client.force_authenticate(user=designer)
        response = api_client.post(
            f"/api/workspaces/{workspace.slug}/invitations/{invite.id}/join/",
            {"accepted": True, "token": invite.token},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        member = WorkspaceMember.objects.get(workspace=workspace, member=designer)
        assert member.role == MEMBER
        assert member.company_role == "Graphic Designer"
