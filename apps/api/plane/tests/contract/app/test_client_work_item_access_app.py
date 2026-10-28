# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Clients (project guests) create work items and edit the ones they created — every detail, the status included."""

from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, State, User, WorkspaceMember

ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/issues/"


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Client Project", identifier="CP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def done_state(project):
    return State.objects.create(project=project, workspace=project.workspace, name="Done", group="completed")


@pytest.fixture
def client_user(db, workspace, project):
    unique_id = uuid4().hex[:8]
    user = User.objects.create(email=f"client-{unique_id}@example.com", username=f"client_{unique_id}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=5)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=5)
    return user


@pytest.fixture
def client_api(client_user):
    api = APIClient()
    api.force_authenticate(user=client_user)
    return api


def _url(workspace, project, issue_id=None):
    url = ISSUES_URL.format(slug=workspace.slug, project_id=project.id)
    return f"{url}{issue_id}/" if issue_id else url


@pytest.mark.contract
class TestClientWorkItemAccess:
    @pytest.mark.django_db
    def test_client_creates_a_work_item(self, client_api, client_user, workspace, project):
        response = client_api.post(_url(workspace, project), {"name": "Logo is blurry"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Issue.objects.get(pk=response.data["id"]).created_by_id == client_user.id

    @pytest.mark.django_db
    def test_client_updates_details_and_status_of_their_work_item(self, client_api, workspace, project, done_state):
        created = client_api.post(_url(workspace, project), {"name": "Logo is blurry"}, format="json").data

        response = client_api.patch(
            _url(workspace, project, created["id"]),
            {"name": "Logo is blurry on mobile", "priority": "high", "state_id": str(done_state.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT, getattr(response, "data", None)
        issue = Issue.objects.get(pk=created["id"])
        assert (issue.name, issue.priority, issue.state_id) == ("Logo is blurry on mobile", "high", done_state.id)

    @pytest.mark.django_db
    def test_client_cannot_update_a_work_item_of_someone_else(self, client_api, workspace, project, create_user):
        issue = Issue.objects.create(name="Set up CI", project=project, workspace=workspace, created_by=create_user)

        response = client_api.patch(_url(workspace, project, issue.id), {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        issue.refresh_from_db()
        assert issue.name == "Set up CI"
