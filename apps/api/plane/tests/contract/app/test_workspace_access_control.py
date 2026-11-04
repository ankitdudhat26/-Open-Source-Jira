# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Settings → Roles & access: admins allow or deny each action of each feature per role, and per person (custom
access). Untouched cells keep the built-in rules; admins and project admins always have full access."""

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, State, User, WorkspaceMember
from plane.utils.access_control import resolve

ACCESS_URL = "/api/workspaces/{slug}/access/"


def _person(workspace, role=15, project=None, project_role=None, is_sub_admin=False):
    user = User.objects.create(email=f"{uuid.uuid4().hex[:10]}@example.com", username=uuid.uuid4().hex)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_sub_admin=is_sub_admin)
    if project:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=project_role or role)
    api = APIClient()
    api.force_authenticate(user=user)
    return user, api


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Web Shop", identifier="SHOP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    State.objects.create(name="Backlog", project=project, workspace=workspace, group="backlog", default=True)
    return project


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.issue.comment.issue_activity.delay"),
        mock.patch("plane.app.views.cycle.base.model_activity.delay"),
        mock.patch("plane.app.views.issue.base.issue_activity.delay"),
    ):
        yield


def _set(admin_api, workspace, role, feature, action, allowed):
    response = admin_api.patch(
        ACCESS_URL.format(slug=workspace.slug),
        {"role": role, "feature": feature, "action": action, "allowed": allowed},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data["rules"]


def _custom(admin_api, workspace, user, feature, action, value):
    response = admin_api.patch(
        f"{ACCESS_URL.format(slug=workspace.slug)}people/{user.id}/",
        {"feature": feature, "action": action, "value": value},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data


def _cycles(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/cycles/"


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("POST", "/api/workspaces/w/projects/{p}/cycles/", ("sprints", "create")),
        ("PATCH", "/api/workspaces/w/projects/{p}/issues/{i}/", ("work_items", "edit")),
        ("POST", "/api/workspaces/w/projects/{p}/issues/{i}/comments/", ("comments", "create")),
        ("DELETE", "/api/workspaces/w/projects/{p}/pages/{i}/", ("pages", "delete")),
        ("POST", "/api/workspaces/w/projects/{p}/modules/{i}/archive/", ("modules", "edit")),
        ("GET", "/api/workspaces/w/projects/{p}/states/", ("project_settings", "view")),
        ("POST", "/api/workspaces/w/projects/", ("projects", "create")),
        ("PATCH", "/api/workspaces/w/projects/{p}/", ("projects", "edit")),
        ("POST", "/api/workspaces/w/invitations/", ("workspace_members", "create")),
        ("GET", "/api/workspaces/w/projects/{p}/user-favorite-cycles/", None),
        ("GET", "/api/workspaces/w/access/me/", None),
    ],
)
def test_requests_are_matched_to_a_feature_and_an_action(method, path, expected):
    request = SimpleNamespace(
        method=method, path=path.format(p="0b758f78-5bf3-49f4-bbec-1d231e96b514", i=str(uuid.uuid4()))
    )

    resolved = resolve(request)

    assert (resolved[2:] if resolved else None) == expected


@pytest.mark.contract
class TestWorkspaceAccessControl:
    @pytest.mark.django_db
    def test_a_denied_action_is_refused_to_the_role_but_not_to_admins(
        self, session_client, workspace, project, create_user
    ):
        _, member_api = _person(workspace, project=project)
        _set(session_client, workspace, "member", "sprints", "create", False)

        refused = member_api.post(_cycles(workspace, project), {"name": "Sprint 1"}, format="json")
        by_admin = session_client.post(_cycles(workspace, project), {"name": "Sprint 2"}, format="json")

        assert refused.status_code == status.HTTP_403_FORBIDDEN
        assert by_admin.status_code == status.HTTP_201_CREATED, by_admin.data

    @pytest.mark.django_db
    def test_project_admins_keep_full_access_to_their_project(self, session_client, workspace, project):
        _, lead_api = _person(workspace, project=project, project_role=20)
        _set(session_client, workspace, "member", "sprints", "create", False)

        response = lead_api.post(_cycles(workspace, project), {"name": "Sprint 1"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data

    @pytest.mark.django_db
    def test_an_allowed_action_is_granted_beyond_the_role(self, session_client, workspace, project, create_user):
        issue = Issue.objects.create(name="Login fails", project=project, workspace=workspace, created_by=create_user)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/comments/"
        _, client_api = _person(workspace, role=5, project=project)

        before = client_api.post(url, {"comment_html": "<p>Still broken</p>"}, format="json")
        _set(session_client, workspace, "client", "comments", "create", True)
        after = client_api.post(url, {"comment_html": "<p>Still broken</p>"}, format="json")

        assert before.status_code == status.HTTP_403_FORBIDDEN
        assert after.status_code == status.HTTP_201_CREATED, after.data

    @pytest.mark.django_db
    def test_custom_access_overrides_the_role_for_one_person(self, session_client, workspace, project, create_user):
        issue = Issue.objects.create(name="Logo", project=project, workspace=workspace, created_by=create_user)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/"
        restricted, restricted_api = _person(workspace, project=project)
        _, other_api = _person(workspace, project=project)
        data = _custom(session_client, workspace, restricted, "work_items", "edit", "deny")

        refused = restricted_api.patch(url, {"name": "Renamed"}, format="json")
        allowed = other_api.patch(url, {"name": "Renamed"}, format="json")

        assert data["access"]["work_items"]["edit"] == {"allowed": False, "set": True}
        assert refused.status_code == status.HTTP_403_FORBIDDEN
        assert allowed.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_custom_access_lets_a_member_create_projects(self, session_client, workspace):
        member, member_api = _person(workspace)
        url = f"/api/workspaces/{workspace.slug}/projects/"

        before = member_api.post(url, {"name": "Side", "identifier": "SIDE"}, format="json")
        _custom(session_client, workspace, member, "projects", "create", "allow")
        after = member_api.post(url, {"name": "Side", "identifier": "SIDE"}, format="json")

        assert before.status_code == status.HTTP_403_FORBIDDEN
        assert after.status_code == status.HTTP_201_CREATED, after.data

    @pytest.mark.django_db
    def test_a_cell_set_back_to_the_built_in_rule_is_not_kept(self, session_client, workspace):
        _set(session_client, workspace, "member", "pages", "delete", False)

        rules = _set(session_client, workspace, "member", "pages", "delete", True)

        assert rules == {}

    @pytest.mark.django_db
    def test_only_admins_manage_access_and_members_read_their_own(self, session_client, workspace):
        _, member_api = _person(workspace)
        _set(session_client, workspace, "member", "pages", "delete", False)

        settings_page = member_api.get(ACCESS_URL.format(slug=workspace.slug))
        change = member_api.patch(
            ACCESS_URL.format(slug=workspace.slug),
            {"role": "member", "feature": "pages", "action": "delete", "allowed": True},
            format="json",
        )
        mine = member_api.get(f"{ACCESS_URL.format(slug=workspace.slug)}me/")

        assert settings_page.status_code == status.HTTP_403_FORBIDDEN
        assert change.status_code == status.HTTP_403_FORBIDDEN
        assert mine.status_code == status.HTTP_200_OK
        assert mine.data["rules"] == {"member": {"pages": {"delete": False}}}

    @pytest.mark.django_db
    def test_admins_cannot_be_restricted(self, session_client, workspace, create_user):
        other_admin, _ = _person(workspace, role=20)

        response = session_client.patch(
            f"{ACCESS_URL.format(slug=workspace.slug)}people/{other_admin.id}/",
            {"feature": "pages", "action": "view", "value": "deny"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_all_projects_shows_every_project_when_allowed(self, session_client, workspace, project):
        # a private project they are not in: only workspace admins see it
        project.network = 0
        project.save(update_fields=["network"])
        member, member_api = _person(workspace)
        url = f"/api/workspaces/{workspace.slug}/projects/"

        before = {item["identifier"] for item in member_api.get(url).data}
        _custom(session_client, workspace, member, "all_projects", "view", "allow")
        after = {item["identifier"] for item in member_api.get(url).data}
        features = {
            item["key"]: item for item in session_client.get(ACCESS_URL.format(slug=workspace.slug)).data["features"]
        }

        assert "SHOP" not in before
        assert "SHOP" in after
        assert features["all_projects"]["action_labels"]["view"].startswith("See the All Projects page")
        assert features["project_settings"]["always_visible"] is True

    @pytest.mark.django_db
    def test_rules_save_again_after_they_were_deleted(self, session_client, workspace):
        from plane.db.models import WorkspaceAccessPolicy

        _set(session_client, workspace, "member", "pages", "delete", False)
        WorkspaceAccessPolicy.objects.get(workspace=workspace).delete()

        rules = _set(session_client, workspace, "member", "all_projects", "view", True)

        assert rules == {"member": {"all_projects": {"view": True}}}
