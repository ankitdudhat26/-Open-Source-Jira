# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import importlib
import uuid

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    Project,
    ProjectMember,
    ProjectWorkflow,
    State,
    User,
    WorkflowTransition,
    WorkspaceMember,
)
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


def reset_to_default(session_client, workspace, project):
    response = session_client.post(url(workspace, project, "workflow/apply-template/"), {"template": "default"})
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data


def moves_of(project, data):
    names = {str(s.id): s.name for s in State.all_state_objects.filter(project=project)}
    return {(names[t["from_state"]], names[t["to_state"]]) for t in data["transitions"]}


NEW_FLOW = {
    ("To Do", "In Progress"),
    ("In Progress", "To Do"),
    ("In Progress", "In QA"),
    ("In QA", "In Progress"),
    ("In QA", "Reopen"),
    ("In QA", "Done"),
    ("Reopen", "In Progress"),
    ("Reopen", "To Do"),
    ("Done", "Reopen"),
    ("Done", "In QA"),
}


def member(workspace, project, role=15):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(email=f"dev-{suffix}@example.com", username=f"dev_{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=role)
    return user


@pytest.mark.contract
class TestProjectWorkflow:
    @pytest.mark.django_db
    def test_a_new_project_starts_with_the_default_workflow(self, session_client, workspace, project):
        data = session_client.get(url(workspace, project, "workflow/")).data
        states = list(State.objects.filter(project=project).order_by("sequence"))

        assert data["is_enabled"] is True
        assert [template["key"] for template in data["templates"]] == ["default"]
        assert data["is_customized"] is False
        assert data["legacy_state_ids"] == []
        # only the five statuses of the new flow (Plane's own Backlog and Cancelled are gone)
        print("STATES", [(s.name, s.group, s.sequence) for s in states])
        assert [(s.name, s.group) for s in states] == [
            ("To Do", "unstarted"),
            ("In Progress", "started"),
            ("In QA", "started"),
            ("Reopen", "started"),
            ("Done", "completed"),
        ]
        assert moves_of(project, data) == NEW_FLOW
        # new work items start in To Do, and skipping steps is refused
        assert State.objects.get(project=project, default=True).name == "To Do"
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace, state=state(project, "To Do"))
        response = session_client.patch(
            url(workspace, project, f"issues/{issue.id}/"), {"state_id": str(state(project, "Done").id)}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_a_project_can_turn_the_workflow_off(self, session_client, workspace, project):
        session_client.put(
            url(workspace, project, "workflow/"), {"is_enabled": False, "transitions": []}, format="json"
        )
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace)
        done = State.objects.filter(project=project, group="completed").first()
        response = session_client.patch(
            url(workspace, project, f"issues/{issue.id}/"), {"state_id": str(done.id)}, format="json"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_the_qa_cycle_of_the_example(self, session_client, workspace, project):
        """TASK-101: To Do → In Progress → In QA → Reopen (QA failed) → In Progress → In QA → Done → Reopen."""
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace, state=state(project, "To Do"))
        issue_url = url(workspace, project, f"issues/{issue.id}/")
        for name in ["In Progress", "In QA", "Reopen", "In Progress", "In QA", "Done", "Reopen"]:
            response = session_client.patch(issue_url, {"state_id": str(state(project, name).id)}, format="json")
            assert response.status_code == status.HTTP_204_NO_CONTENT, (name, response.data)
        # Reopen goes back to development or the queue, not straight to Done
        response = session_client.patch(issue_url, {"state_id": str(state(project, "Done").id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_only_permitted_moves_are_allowed(self, session_client, workspace, project):
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
        todo, done = state(project, "To Do"), State.objects.filter(project=project, group="completed").first()
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
        reviewer, developer = member(workspace, project), member(workspace, project)
        qa, done = state(project, "In QA"), state(project, "Done")
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
        todo = state(project, "To Do")

        response = session_client.put(
            url(workspace, project, "workflow/"),
            {"is_enabled": True, "transitions": [{"from_state": str(todo.id), "to_state": str(foreign_state.id)}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_automation_is_not_blocked_by_the_workflow(self, session_client, workspace, project, create_user):
        feature = Issue.objects.create(
            name="Login", project=project, workspace=workspace, state=state(project, "To Do")
        )
        task = Issue.objects.create(
            name="API", project=project, workspace=workspace, parent=feature, state=state(project, "Done")
        )

        run_work_item_automation(task.id, create_user.id, state_changed=True)

        feature.refresh_from_db()
        assert feature.state.group == "completed"


def old_project(workspace, name="Jira clone", identifier="JIRA", customized=False):
    """A project from before: Jira's statuses (some with work items) and its own rules."""
    project = Project.objects.create(name=name, identifier=identifier, workspace=workspace)
    created = {}
    for sequence, (state_name, group) in enumerate(
        [
            ("Backlog", "backlog"),
            ("Open", "unstarted"),
            ("To Do", "unstarted"),
            ("In Progress", "started"),
            ("IN QA", "started"),
            ("Reopened", "started"),
            ("Waiting for Demo", "started"),
            ("Closed", "completed"),
            ("Done", "completed"),
            ("Invalid", "cancelled"),
            ("Cancelled", "cancelled"),
        ]
    ):
        created[state_name] = State.objects.create(
            name=state_name, group=group, project=project, workspace=workspace, sequence=sequence * 1000
        )
    for state_name in ["Open", "IN QA", "Reopened", "Waiting for Demo", "Closed", "Invalid"]:
        Issue.objects.create(name=state_name, project=project, workspace=workspace, state=created[state_name])
    ProjectWorkflow.objects.create(project=project, workspace=workspace, is_enabled=True, is_customized=customized)
    WorkflowTransition.objects.create(
        project=project, workspace=workspace, from_state=created["Open"], to_state=created["Closed"]
    )
    return project


@pytest.mark.contract
class TestNewDefaultWorkflowForExistingProjects:
    """Every existing project (also a customized one or a Jira clone) moves to the new flow and keeps only its five
    statuses: every other status is merged into the one it stands for, with its work items."""

    def check(self, session_client, workspace, project):
        data = session_client.get(url(workspace, project, "workflow/")).data
        names = [s.name for s in State.objects.filter(project=project).order_by("sequence")]

        assert names == ["To Do", "In Progress", "In QA", "Reopen", "Done"]
        assert data["legacy_state_ids"] == []
        assert data["is_enabled"] is True and data["is_customized"] is False
        assert moves_of(project, data) == NEW_FLOW
        # every work item is in one of the five
        placed = {issue.name: issue.state.name for issue in Issue.objects.filter(project=project)}
        assert placed == {
            "Open": "To Do",
            "IN QA": "In QA",
            "Reopened": "Reopen",
            "Waiting for Demo": "In QA",
            "Closed": "Done",
            "Invalid": "Done",
        }
        assert State.objects.get(project=project, default=True).name == "To Do"

    @pytest.mark.django_db
    def test_reset_moves_an_old_project_to_the_new_flow(self, session_client, workspace):
        project = old_project(workspace, customized=True)
        ProjectMember.objects.create(workspace=workspace, project=project, member=workspace.owner, role=20)
        reset_to_default(session_client, workspace, project)
        self.check(session_client, workspace, project)

    @pytest.mark.django_db
    def test_the_migration_moves_every_project_also_customized_ones(self, session_client, workspace):
        from django.db.migrations.loader import MigrationLoader
        from django.test import override_settings
        from django.utils import timezone

        # the models as the migration sees them (no custom managers); the tests run without migrations, so the
        # migration graph is read here
        with override_settings(MIGRATION_MODULES={}):
            apps = MigrationLoader(None).project_state(("db", "0141_new_default_workflow")).apps

        migration = importlib.import_module("plane.db.migrations.0141_new_default_workflow")
        projects = [old_project(workspace, customized=False), old_project(workspace, "Own", "OWN", customized=True)]
        for project in projects:
            ProjectMember.objects.create(workspace=workspace, project=project, member=workspace.owner, role=20)
            migration.adopt(apps, project, timezone.now())
            self.check(session_client, workspace, project)


@pytest.mark.contract
class TestCustomizedWorkflow:
    """A project follows the default workflow until its states or moves are changed in its settings."""

    @pytest.mark.django_db
    def test_saving_moves_or_renaming_a_state_makes_it_the_projects_own(self, session_client, workspace, project):
        def customized():
            return session_client.get(url(workspace, project, "workflow/")).data["is_customized"]

        in_qa = state(project, "In QA")
        # a new colour is not a customization
        session_client.patch(url(workspace, project, f"states/{in_qa.id}/"), {"color": "#000000"}, format="json")
        assert customized() is False

        session_client.patch(url(workspace, project, f"states/{in_qa.id}/"), {"name": "Testing"}, format="json")
        assert customized() is True

        # back to the default: it follows the default again (missing states are added back)
        response = session_client.post(url(workspace, project, "workflow/apply-template/"), {"template": "default"})
        assert response.data["is_customized"] is False
        assert State.objects.filter(project=project, name="In QA").exists()

        data = session_client.get(url(workspace, project, "workflow/")).data
        session_client.put(
            url(workspace, project, "workflow/"),
            {"is_enabled": True, "transitions": data["transitions"][:-1]},
            format="json",
        )
        assert customized() is True

    @pytest.mark.django_db
    def test_deleting_an_unused_state_drops_its_moves(self, session_client, workspace, project):
        reopened = state(project, "Reopen")

        response = session_client.delete(url(workspace, project, f"states/{reopened.id}/"))
        data = session_client.get(url(workspace, project, "workflow/")).data

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert str(reopened.id) not in {t["from_state"] for t in data["transitions"]} | {
            t["to_state"] for t in data["transitions"]
        }
        assert data["is_customized"] is True

    @pytest.mark.django_db
    def test_deleting_a_status_with_work_items_moves_them_first(self, session_client, workspace, project):
        extra = State.objects.create(name="Blocked", group="started", project=project, workspace=workspace)
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace, state=extra)
        delete_url = url(workspace, project, f"states/{extra.id}/")

        refused = session_client.delete(delete_url)
        moved = session_client.delete(f"{delete_url}?move_to={state(project, 'In Progress').id}")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert "Choose the status" in refused.data["error"]
        assert moved.status_code == status.HTTP_204_NO_CONTENT
        issue.refresh_from_db()
        assert issue.state.name == "In Progress"
        assert not State.objects.filter(pk=extra.pk).exists()


def test_every_old_status_has_a_place_in_the_new_flow():
    from plane.utils.workflow import default_status_for

    # statuses found in the projects today
    assert {
        name: default_status_for(name, group)
        for name, group in [
            ("Backlog", "backlog"),
            ("Story Detailing", "unstarted"),
            ("Selected for Development", "unstarted"),
            ("Open", "unstarted"),
            ("In Development", "started"),
            ("Prototyping", "started"),
            ("IN QA", "started"),
            ("QA", "started"),
            ("QA release", "started"),
            ("Resolved", "started"),
            ("Waiting for Demo", "started"),
            ("Dev/Design Done", "started"),
            ("Testing / QA", "started"),
            ("QA Failed", "started"),
            ("Re-open", "started"),
            ("in production", "started"),
            ("Closed", "completed"),
            ("UAT", "completed"),
            ("Client Review", "completed"),
            ("Ready for Deployment", "completed"),
            ("UAT Fail by DHSPL", "completed"),
            ("Invalid", "cancelled"),
            ("Cancelled", "cancelled"),
        ]
    } == {
        "Backlog": "To Do",
        "Story Detailing": "To Do",
        "Selected for Development": "To Do",
        "Open": "To Do",
        "In Development": "In Progress",
        "Prototyping": "In Progress",
        "IN QA": "In QA",
        "QA": "In QA",
        "QA release": "In QA",
        "Resolved": "In QA",
        "Waiting for Demo": "In QA",
        "Dev/Design Done": "In QA",
        "Testing / QA": "In QA",
        "QA Failed": "Reopen",
        "Re-open": "Reopen",
        "in production": "Done",
        "Closed": "Done",
        "UAT": "Done",
        "Client Review": "Done",
        "Ready for Deployment": "Done",
        "UAT Fail by DHSPL": "Reopen",
        "Invalid": "Done",
        "Cancelled": "Done",
    }
