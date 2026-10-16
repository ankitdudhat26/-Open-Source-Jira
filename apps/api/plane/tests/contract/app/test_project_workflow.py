# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

import pytest
from rest_framework import status

from plane.db.models import Issue, Project, ProjectMember, State, User, WorkspaceMember
from plane.utils.work_item_automation import run_work_item_automation


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Flow", "identifier": "FLOW"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def url(workspace, project, path=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/{path}"


def state(project, name):
    return State.objects.get(project=project, name=name)


def apply_software_workflow(session_client, workspace, project):
    response = session_client.post(url(workspace, project, "workflow/apply-template/"), {"template": "software"})
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data


def member(workspace, project, role=15):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(email=f"dev-{suffix}@example.com", username=f"dev_{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=role)
    return user


@pytest.mark.contract
class TestProjectWorkflow:
    @pytest.mark.django_db
    def test_workflow_is_off_by_default_and_anything_goes(self, session_client, workspace, project):
        data = session_client.get(url(workspace, project, "workflow/")).data
        assert data["is_enabled"] is False
        assert data["transitions"] == []
        assert {template["key"] for template in data["templates"]} == {"software", "simple"}

        issue = Issue.objects.create(name="Login", project=project, workspace=workspace)
        done = State.objects.filter(project=project, group="completed").first()
        response = session_client.patch(
            url(workspace, project, f"issues/{issue.id}/"), {"state_id": str(done.id)}, format="json"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_template_adds_missing_states_and_turns_the_workflow_on(self, session_client, workspace, project):
        data = apply_software_workflow(session_client, workspace, project)

        names = set(State.objects.filter(project=project).values_list("name", flat=True))
        assert {"Backlog", "To Do", "In Progress", "In Review", "QA", "Done", "Cancelled"} <= names
        assert data["is_enabled"] is True
        backlog, todo = state(project, "Backlog"), state(project, "To Do")
        assert {"from_state": str(backlog.id), "to_state": str(todo.id)} in [
            {"from_state": t["from_state"], "to_state": t["to_state"]} for t in data["transitions"]
        ]
        # applying twice does not duplicate states
        apply_software_workflow(session_client, workspace, project)
        assert State.objects.filter(project=project, name="QA").count() == 1

    @pytest.mark.django_db
    def test_only_permitted_moves_are_allowed(self, session_client, workspace, project):
        apply_software_workflow(session_client, workspace, project)
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace, state=state(project, "To Do"))
        issue_url = url(workspace, project, f"issues/{issue.id}/")

        response = session_client.patch(issue_url, {"state_id": str(state(project, "Done").id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "WORKFLOW_TRANSITION_NOT_ALLOWED"
        assert "To Do to Done" in response.data["error"]
        issue.refresh_from_db()
        assert issue.state.name == "To Do"

        response = session_client.patch(issue_url, {"state_id": str(state(project, "In Progress").id)}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        # other fields are not affected by the workflow
        response = session_client.patch(issue_url, {"priority": "high"}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_state_without_rules_is_not_restricted(self, session_client, workspace, project):
        todo, done = state(project, "Todo"), State.objects.filter(project=project, group="completed").first()
        in_progress = State.objects.filter(project=project, group="started").first()
        session_client.put(
            url(workspace, project, "workflow/"),
            {"is_enabled": True, "transitions": [{"from_state": str(todo.id), "to_state": str(in_progress.id)}]},
            format="json",
        )
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace, state=in_progress)

        response = session_client.patch(
            url(workspace, project, f"issues/{issue.id}/"), {"state_id": str(done.id)}, format="json"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_reviewers_limit_who_can_move(self, session_client, api_client, workspace, project):
        apply_software_workflow(session_client, workspace, project)
        reviewer, developer = member(workspace, project), member(workspace, project)
        qa, done = state(project, "QA"), state(project, "Done")
        data = session_client.get(url(workspace, project, "workflow/")).data
        transitions = [
            {**t, "reviewer_ids": [str(reviewer.id)]}
            if (t["from_state"], t["to_state"]) == (str(qa.id), str(done.id))
            else t
            for t in data["transitions"]
        ]
        session_client.put(
            url(workspace, project, "workflow/"), {"is_enabled": True, "transitions": transitions}, format="json"
        )
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace, state=qa)
        issue_url = url(workspace, project, f"issues/{issue.id}/")

        api_client.force_authenticate(user=developer)
        response = api_client.patch(issue_url, {"state_id": str(done.id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "reviewers" in response.data["error"]

        api_client.force_authenticate(user=reviewer)
        assert (
            api_client.patch(issue_url, {"state_id": str(done.id)}, format="json").status_code
            == status.HTTP_204_NO_CONTENT
        )

    @pytest.mark.django_db
    def test_only_admins_can_change_the_workflow(self, api_client, session_client, workspace, project):
        developer = member(workspace, project)
        api_client.force_authenticate(user=developer)

        assert api_client.get(url(workspace, project, "workflow/")).status_code == status.HTTP_200_OK
        response = api_client.put(url(workspace, project, "workflow/"), {"is_enabled": True}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_invalid_transitions_are_rejected(self, session_client, workspace, project):
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        foreign_state = State.objects.create(name="Foreign", project=other, workspace=workspace, group="started")
        todo = state(project, "Todo")

        response = session_client.put(
            url(workspace, project, "workflow/"),
            {"is_enabled": True, "transitions": [{"from_state": str(todo.id), "to_state": str(foreign_state.id)}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_automation_is_not_blocked_by_the_workflow(self, session_client, workspace, project, create_user):
        apply_software_workflow(session_client, workspace, project)
        feature = Issue.objects.create(
            name="Login", project=project, workspace=workspace, state=state(project, "To Do")
        )
        task = Issue.objects.create(
            name="API", project=project, workspace=workspace, parent=feature, state=state(project, "Done")
        )

        run_work_item_automation(task.id, create_user.id, state_changed=True)

        feature.refresh_from_db()
        assert feature.state.group == "completed"
