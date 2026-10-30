# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Clients (project guests) only view a project's work items: they cannot create, edit or comment on them, and they
do not use the project's Intake (requests come in through the Intake form's link instead)."""

from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Intake, Issue, Project, ProjectMember, User, WorkspaceMember

ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/issues/"


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Client Project", identifier="CP", workspace=workspace, created_by=create_user, intake_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    Intake.objects.create(name="Client Project Intake", project=project, is_default=True)
    return project


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
    def test_client_views_work_items(self, client_api, workspace, project, create_user):
        issue = Issue.objects.create(name="Set up CI", project=project, workspace=workspace, created_by=create_user)

        response = client_api.get(_url(workspace, project, issue.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Set up CI"

    @pytest.mark.django_db
    def test_client_cannot_create_a_work_item(self, client_api, workspace, project):
        response = client_api.post(_url(workspace, project), {"name": "Logo is blurry"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Issue.objects.filter(project=project, name="Logo is blurry").exists()

    @pytest.mark.django_db
    def test_client_cannot_update_even_a_work_item_they_created(self, client_api, client_user, workspace, project):
        issue = Issue.objects.create(name="Old request", project=project, workspace=workspace, created_by=client_user)

        response = client_api.patch(_url(workspace, project, issue.id), {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        issue.refresh_from_db()
        assert issue.name == "Old request"

    @pytest.mark.django_db
    def test_client_cannot_comment(self, client_api, workspace, project, create_user):
        issue = Issue.objects.create(name="Set up CI", project=project, workspace=workspace, created_by=create_user)

        response = client_api.post(
            f"{_url(workspace, project, issue.id)}comments/", {"comment_html": "<p>Hi</p>"}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_client_does_not_use_the_project_intake(self, client_api, workspace, project):
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/intake-issues/"

        assert client_api.get(url).status_code == status.HTTP_403_FORBIDDEN
        assert client_api.post(url, {"issue": {"name": "Request"}}, format="json").status_code == 403
