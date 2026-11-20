# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Accepting, declining, snoozing and marking a request as duplicate in Intake is for the project's admins only: the
people whose Role is Admin in the project's Members. Everyone else (a project member, or a workspace admin who is a
member of this project) cannot, though the person who sent a request can still edit it."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Intake,
    IntakeIssue,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceAccessPolicy,
    WorkspaceMember,
)

INTAKE_ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-issues/"


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        patch("plane.app.views.intake.base.issue_activity.delay"),
        patch("plane.app.views.intake.base.issue_description_version_task.delay"),
        patch("plane.app.views.intake.base.intake_request_status.delay"),
    ):
        yield


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Support Desk", identifier="SD", workspace=workspace, created_by=create_user, intake_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    Intake.objects.create(name="Support Desk Intake", project=project, is_default=True)
    State.objects.create(name="To Do", group="unstarted", project=project, workspace=workspace, default=True)
    return project


@pytest.fixture
def url(workspace, project):
    return INTAKE_ISSUES_URL.format(slug=workspace.slug, project_id=project.id)


def _person(workspace, project, workspace_role, project_role):
    unique_id = uuid4().hex[:8]
    user = User.objects.create(email=f"person-{unique_id}@example.com", username=f"person_{unique_id}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=workspace_role)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=project_role)
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _request(api, url, name="Invoice mail body changes"):
    response = api.post(url, {"issue": {"name": name}}, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data["issue"]["id"]


@pytest.mark.contract
class TestIntakeTriageIsForProjectAdmins:
    @pytest.mark.django_db
    def test_project_admin_accepts(self, session_client, url):
        issue_id = _request(session_client, url)

        response = session_client.patch(f"{url}{issue_id}/", {"status": 1}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.data
        assert IntakeIssue.objects.get(issue_id=issue_id).status == 1

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "change",
        [
            {"status": 1},
            {"status": -1, "decline_reason": "Out of scope"},
            {"status": 0, "snoozed_till": "2030-01-01T00:00:00Z"},
            {"status": 2, "duplicate_to": None},
        ],
    )
    def test_project_member_cannot_triage_even_their_own_request(self, workspace, project, url, change):
        member = _person(workspace, project, workspace_role=15, project_role=15)
        issue_id = _request(member, url)

        response = member.patch(f"{url}{issue_id}/", change, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert IntakeIssue.objects.get(issue_id=issue_id).status == -2

    @pytest.mark.django_db
    def test_workspace_admin_who_is_a_member_of_the_project_cannot_triage(
        self, session_client, workspace, project, url
    ):
        workspace_admin = _person(workspace, project, workspace_role=20, project_role=15)
        issue_id = _request(session_client, url)

        response = workspace_admin.patch(f"{url}{issue_id}/", {"status": 1}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert IntakeIssue.objects.get(issue_id=issue_id).status == -2

    @pytest.mark.django_db
    def test_member_still_edits_their_own_request(self, workspace, project, url):
        member = _person(workspace, project, workspace_role=15, project_role=15)
        issue_id = _request(member, url)

        response = member.patch(f"{url}{issue_id}/", {"issue": {"name": "Invoice mail body"}}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["issue"]["name"] == "Invoice mail body"

    @pytest.mark.django_db
    def test_project_admin_with_a_member_workspace_role_triages_though_members_cannot(
        self, session_client, workspace, project, url
    ):
        """Like Rajendra on live: Member of the workspace, Admin of the project; Roles & access denies Members Intake
        Edit. The Members list decides: they accept, a Member still cannot."""
        WorkspaceAccessPolicy.objects.create(
            workspace=workspace, rules={"member": {"intake": {"edit": False, "create": False, "delete": False}}}
        )
        project_admin = _person(workspace, project, workspace_role=15, project_role=20)
        member = _person(workspace, project, workspace_role=15, project_role=15)
        issue_id = _request(session_client, url)

        refused = member.patch(f"{url}{issue_id}/", {"status": 1}, format="json")
        accepted = project_admin.patch(f"{url}{issue_id}/", {"status": 1}, format="json")

        assert refused.status_code == status.HTTP_403_FORBIDDEN
        assert accepted.status_code == status.HTTP_200_OK, accepted.data
        assert IntakeIssue.objects.get(issue_id=issue_id).status == 1
