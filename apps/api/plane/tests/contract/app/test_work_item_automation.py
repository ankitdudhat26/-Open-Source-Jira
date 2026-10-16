# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import Cycle, CycleIssue, Issue, Project, State
from plane.utils.work_item_automation import run_work_item_automation


def _create_project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Automation", "identifier": "AUTO"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def _state(project, group):
    return State.objects.filter(project=project, group=group).order_by("sequence").first()


def _issue(project, name, parent=None, group="backlog"):
    return Issue.objects.create(
        name=name, project=project, workspace=project.workspace, parent=parent, state=_state(project, group)
    )


def _group(issue):
    issue.refresh_from_db()
    return issue.state.group


def _issue_url(workspace, project, issue=None):
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"
    return f"{base}{issue.id}/" if issue else base


@pytest.fixture
def project(session_client, workspace):
    return _create_project(session_client, workspace)


@pytest.mark.contract
class TestParentStatusAutomation:
    @pytest.mark.django_db
    def test_feature_completes_when_all_tasks_are_done(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        task_a = _issue(project, "API", parent=feature)
        task_b = _issue(project, "UI", parent=feature)
        done = _state(project, "completed")

        session_client.patch(_issue_url(workspace, project, task_a), {"state_id": str(done.id)}, format="json")
        # one task still open, the feature is in progress now
        assert _group(feature) == "started"

        response = session_client.patch(
            _issue_url(workspace, project, task_b), {"state_id": str(done.id)}, format="json"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        feature.refresh_from_db()
        assert feature.state_id == done.id
        assert feature.completed_at is not None

    @pytest.mark.django_db
    def test_feature_starts_when_a_task_starts(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        task = _issue(project, "API", parent=feature)
        _issue(project, "UI", parent=feature)

        session_client.patch(
            _issue_url(workspace, project, task), {"state_id": str(_state(project, "started").id)}, format="json"
        )
        assert _group(feature) == "started"

    @pytest.mark.django_db
    def test_reopening_a_task_reopens_the_done_feature(self, session_client, workspace, project):
        feature = _issue(project, "Login", group="completed")
        task = _issue(project, "API", parent=feature, group="completed")

        session_client.patch(
            _issue_url(workspace, project, task), {"state_id": str(_state(project, "unstarted").id)}, format="json"
        )
        assert _group(feature) == "started"

    @pytest.mark.django_db
    def test_new_task_under_a_done_feature_reopens_it(self, session_client, workspace, project):
        feature = _issue(project, "Login", group="completed")
        _issue(project, "API", parent=feature, group="completed")

        response = session_client.post(
            _issue_url(workspace, project), {"name": "Forgot password", "parent_id": str(feature.id)}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _group(feature) == "started"

    @pytest.mark.django_db
    def test_only_cancelled_tasks_do_not_complete_the_feature(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        task = _issue(project, "API", parent=feature)

        session_client.patch(
            _issue_url(workspace, project, task), {"state_id": str(_state(project, "cancelled").id)}, format="json"
        )
        assert _group(feature) == "backlog"

    @pytest.mark.django_db
    def test_status_rolls_up_through_every_level(self, session_client, workspace, project, create_user):
        epic = _issue(project, "Auth")
        feature = _issue(project, "Login", parent=epic)
        task = _issue(project, "API", parent=feature)
        task.state = _state(project, "completed")
        task.save()

        run_work_item_automation(task.id, create_user.id, state_changed=True)

        assert _group(feature) == "completed"
        assert _group(epic) == "completed"

    @pytest.mark.django_db
    def test_moving_the_last_open_task_away_completes_the_old_feature(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        other = _issue(project, "Signup")
        _issue(project, "API", parent=feature, group="completed")
        open_task = _issue(project, "UI", parent=feature)

        session_client.patch(_issue_url(workspace, project, open_task), {"parent_id": str(other.id)}, format="json")
        assert _group(feature) == "completed"


def _cycle(project, name="Sprint 1", days=14):
    return Cycle.objects.create(
        name=name,
        project=project,
        workspace=project.workspace,
        start_date=timezone.now() - timedelta(days=1),
        end_date=timezone.now() + timedelta(days=days),
        owned_by=project.created_by,
    )


def _cycle_issue_ids(cycle):
    return set(CycleIssue.objects.filter(cycle=cycle).values_list("issue_id", flat=True))


@pytest.mark.contract
class TestSprintFollowsFeature:
    @pytest.mark.django_db
    def test_adding_a_feature_adds_all_its_tasks(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        task = _issue(project, "API", parent=feature)
        sub_task = _issue(project, "Endpoint", parent=task)
        unrelated = _issue(project, "Other")
        sprint = _cycle(project)

        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/cycles/{sprint.id}/cycle-issues/",
            {"issues": [str(feature.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _cycle_issue_ids(sprint) == {feature.id, task.id, sub_task.id}
        assert set(response.data["issues"]) == {str(feature.id), str(task.id), str(sub_task.id)}
        assert unrelated.id not in _cycle_issue_ids(sprint)

    @pytest.mark.django_db
    def test_tasks_move_with_the_feature_to_another_sprint(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        task = _issue(project, "API", parent=feature)
        sprint_1 = _cycle(project, "Sprint 1")
        sprint_2 = _cycle(project, "Sprint 2", days=28)
        url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/cycles/{{}}/cycle-issues/"

        session_client.post(url.format(sprint_1.id), {"issues": [str(feature.id)]}, format="json")
        session_client.post(url.format(sprint_2.id), {"issues": [str(feature.id)]}, format="json")

        assert _cycle_issue_ids(sprint_1) == set()
        assert _cycle_issue_ids(sprint_2) == {feature.id, task.id}

    @pytest.mark.django_db
    def test_removing_a_feature_removes_its_tasks(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        _issue(project, "API", parent=feature)
        sprint = _cycle(project)
        base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/cycles/{sprint.id}/cycle-issues/"
        session_client.post(base, {"issues": [str(feature.id)]}, format="json")

        response = session_client.delete(f"{base}{feature.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert _cycle_issue_ids(sprint) == set()

    @pytest.mark.django_db
    def test_new_task_joins_the_feature_sprint(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        sprint = _cycle(project)
        CycleIssue.objects.create(cycle=sprint, issue=feature, project=project, workspace=project.workspace)

        response = session_client.post(
            _issue_url(workspace, project), {"name": "API", "parent_id": str(feature.id)}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert CycleIssue.objects.filter(cycle=sprint, issue_id=response.data["id"]).exists()
        assert str(response.data["cycle_id"]) == str(sprint.id)

    @pytest.mark.django_db
    def test_task_moved_under_a_feature_joins_its_sprint(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        task = _issue(project, "API")
        sprint = _cycle(project)
        CycleIssue.objects.create(cycle=sprint, issue=feature, project=project, workspace=project.workspace)

        session_client.patch(_issue_url(workspace, project, task), {"parent_id": str(feature.id)}, format="json")

        assert CycleIssue.objects.filter(cycle=sprint, issue=task).exists()

    @pytest.mark.django_db
    def test_finished_sprint_is_not_joined(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        sprint = _cycle(project, days=-1)
        CycleIssue.objects.create(cycle=sprint, issue=feature, project=project, workspace=project.workspace)

        response = session_client.post(
            _issue_url(workspace, project), {"name": "API", "parent_id": str(feature.id)}, format="json"
        )

        assert not CycleIssue.objects.filter(issue_id=response.data["id"]).exists()


@pytest.mark.contract
class TestSprintBoard:
    @pytest.mark.django_db
    def test_board_lists_sprint_items_with_their_parent_features(self, session_client, workspace, project):
        feature = _issue(project, "Login")
        in_sprint = _issue(project, "API", parent=feature)
        _issue(project, "UI", parent=feature)  # task of the same feature, not in the sprint
        other = _issue(project, "Other")
        sprint = _cycle(project)
        CycleIssue.objects.create(cycle=sprint, issue=in_sprint, project=project, workspace=project.workspace)
        CycleIssue.objects.create(cycle=sprint, issue=other, project=project, workspace=project.workspace)

        response = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/cycles/{sprint.id}/sprint-board/"
        )

        assert response.status_code == status.HTTP_200_OK
        rows = {str(row["id"]): row for row in response.data}
        assert set(rows) == {str(feature.id), str(in_sprint.id), str(other.id)}
        assert rows[str(feature.id)]["in_sprint"] is False
        assert rows[str(in_sprint.id)]["in_sprint"] is True
        assert str(rows[str(in_sprint.id)]["parent_id"]) == str(feature.id)
