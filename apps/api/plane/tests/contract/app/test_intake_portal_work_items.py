# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The client's side of the Intake link beyond requests: the Work Items tab (the work items they may see, as in the
app), a work item's details where they comment, attach files and move it to another state (the workflow decides
which), their notifications — and, for the team, who sent each request and an email to them when it is decided."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Intake,
    IntakeIssue,
    Issue,
    IssueActivity,
    IssueComment,
    Project,
    ProjectMember,
    ProjectWorkflow,
    State,
    User,
    WorkflowTransition,
)

FORM_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-form/"
INTAKE_ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-issues/"
PORTAL_URL = "/api/public/intake-forms/{anchor}/"


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        patch("plane.app.views.intake.base.issue_activity.delay"),
        patch("plane.app.views.intake.base.issue_description_version_task.delay"),
        patch("plane.app.views.intake.base.intake_request_status.delay") as status_email,
        patch("plane.space.views.intake_form.issue_activity.delay"),
        patch("plane.app.views.intake.form.intake_form_invitation.delay"),
    ):
        yield status_email


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Customer App", identifier="CA", workspace=workspace, created_by=create_user, intake_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    Intake.objects.create(name="Customer App Intake", project=project, is_default=True)
    for index, (name, group) in enumerate(
        [("To Do", "unstarted"), ("In Progress", "started"), ("In QA", "started"), ("Done", "completed")]
    ):
        State.objects.create(
            name=name, group=group, project=project, workspace=workspace, sequence=index, default=name == "To Do"
        )
    return project


@pytest.fixture
def client_user(db):
    unique_id = uuid4().hex[:8]
    return User.objects.create(
        email=f"client-{unique_id}@example.com", username=f"client_{unique_id}", first_name="Riya", last_name="Shah"
    )


@pytest.fixture
def client_api(client_user):
    api = APIClient()
    api.force_authenticate(user=client_user)
    return api


@pytest.fixture
def anchor(session_client, workspace, project, client_user):
    form_url = FORM_URL.format(slug=workspace.slug, project_id=project.id)
    response = session_client.patch(form_url, {"is_enabled": True}, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data
    session_client.post(f"{form_url}invites/", {"emails": [client_user.email]}, format="json")
    return response.data["anchor"]


def _send(client_api, anchor, name="Login button does nothing"):
    response = client_api.post(f"{PORTAL_URL.format(anchor=anchor)}requests/", {"issue": {"name": name}}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data["issue_id"]


def _decide(session_client, workspace, project, issue_id, **data):
    url = f"{INTAKE_ISSUES_URL.format(slug=workspace.slug, project_id=project.id)}{issue_id}/"
    response = session_client.patch(url, data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data
    return response


def _work_items(client_api, anchor):
    return client_api.get(f"{PORTAL_URL.format(anchor=anchor)}work-items/").data


@pytest.mark.contract
class TestClientWorkItems:
    @pytest.mark.django_db
    def test_the_client_sees_the_same_work_items_as_the_team(
        self, session_client, workspace, project, anchor, client_api
    ):
        accepted = _send(client_api, anchor, "Accepted one")
        _send(client_api, anchor, "Still pending")
        _decide(session_client, workspace, project, accepted, status=1)
        Issue.objects.create(
            name="Team task", project=project, workspace=workspace, state=State.objects.get(name="To Do")
        )

        items = _work_items(client_api, anchor)

        # a request still waiting in Intake is not a work item yet
        assert {(item["name"], item["state"]["name"]) for item in items} == {
            ("Accepted one", "To Do"),
            ("Team task", "To Do"),
        }
        assert {"modules", "sprint", "parent", "milestone"} <= set(items[0])
        # the client's own work items are marked, with who created each one
        mine = {item["name"]: (item["is_mine"], (item["created_by"] or {}).get("name")) for item in items}
        assert mine["Accepted one"] == (True, "Riya Shah")
        assert mine["Team task"][0] is False

    @pytest.mark.django_db
    def test_client_comments_attaches_and_moves_the_state_the_workflow_allows(
        self, session_client, workspace, project, anchor, client_api, client_user
    ):
        issue_id = _send(client_api, anchor)
        _decide(session_client, workspace, project, issue_id, status=1)
        to_do, in_progress, done = (
            State.objects.get(project=project, name=name) for name in ("To Do", "In Progress", "Done")
        )
        ProjectWorkflow.objects.create(project=project, workspace=workspace, is_enabled=True)
        WorkflowTransition.objects.create(project=project, workspace=workspace, from_state=to_do, to_state=in_progress)
        url = f"{PORTAL_URL.format(anchor=anchor)}work-items/{issue_id}/"

        detail = client_api.get(url).data
        refused = client_api.patch(url, {"state_id": str(done.id)}, format="json")
        other_field = client_api.patch(url, {"name": "Renamed"}, format="json")
        moved = client_api.patch(url, {"state_id": str(in_progress.id)}, format="json")
        comment = client_api.post(f"{url}comments/", {"comment_html": "<p>Works on Chrome now</p>"}, format="json")
        with patch("plane.space.views.intake_form.S3Storage.upload_file", return_value=True):
            attached = client_api.post(
                f"{url}attachments/", {"file": SimpleUploadedFile("log.txt", b"trace", content_type="text/plain")}
            )

        assert [state["name"] for state in detail["allowed_states"]] == ["In Progress"]
        assert detail["created_by"]["name"] == "Riya Shah"
        assert detail["is_mine"] is True
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert other_field.status_code == status.HTTP_400_BAD_REQUEST
        assert moved.status_code == status.HTTP_200_OK, moved.data
        assert moved.data["state"]["name"] == "In Progress"
        assert comment.status_code == status.HTTP_201_CREATED, comment.data
        assert IssueComment.objects.get(issue_id=issue_id).actor == client_user
        assert attached.status_code == status.HTTP_201_CREATED, attached.data

    @pytest.mark.django_db
    def test_work_items_of_other_projects_are_not_found(self, session_client, workspace, project, anchor, client_api):
        other = Project.objects.create(name="Other", identifier="OT", workspace=workspace)
        foreign = Issue.objects.create(name="Not theirs", project=other, workspace=workspace)

        response = client_api.get(f"{PORTAL_URL.format(anchor=anchor)}work-items/{foreign.id}/")
        comment = client_api.post(
            f"{PORTAL_URL.format(anchor=anchor)}work-items/{foreign.id}/comments/", {"comment_html": "<p>Hi</p>"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert comment.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
class TestClientNotificationsAndTeamSide:
    @pytest.mark.django_db
    def test_notifications_list_decisions_and_what_the_team_did(
        self, session_client, workspace, project, anchor, client_api, create_user
    ):
        accepted = _send(client_api, anchor, "Accepted one")
        declined = _send(client_api, anchor, "Declined one")
        _decide(session_client, workspace, project, accepted, status=1)
        _decide(session_client, workspace, project, declined, status=-1, decline_reason="Out of scope")
        IssueActivity.objects.create(
            issue_id=accepted,
            project=project,
            workspace=workspace,
            actor=create_user,
            verb="updated",
            field="state",
            old_value="To Do",
            new_value="In Progress",
        )

        events = client_api.get(f"{PORTAL_URL.format(anchor=anchor)}notifications/").data
        texts = {event["text"] for event in events}

        assert "Your request was accepted." in texts
        assert "Your request was declined: Out of scope" in texts
        assert any(text.endswith("moved it from To Do to In Progress") for text in texts)

    @pytest.mark.django_db
    def test_the_team_sees_who_sent_the_request_and_they_are_emailed_the_decision(
        self,
        session_client,
        workspace,
        project,
        anchor,
        client_api,
        client_user,
        no_background_tasks,
        django_capture_on_commit_callbacks,
    ):
        issue_id = _send(client_api, anchor)
        listed = session_client.get(INTAKE_ISSUES_URL.format(slug=workspace.slug, project_id=project.id)).data

        with django_capture_on_commit_callbacks(execute=True):
            _decide(session_client, workspace, project, issue_id, status=1)

        creators = [item["created_by_detail"]["email"] for item in listed["results"]]
        assert creators == [client_user.email]
        intake_issue = IntakeIssue.objects.get(issue_id=issue_id)
        no_background_tasks.assert_called_once()
        assert no_background_tasks.call_args.args[0] == str(intake_issue.id)
        assert f"intake/{anchor}" in no_background_tasks.call_args.args[2]

    @pytest.mark.django_db
    def test_the_team_sees_the_client_as_created_by_on_the_work_item(
        self, session_client, workspace, project, anchor, client_api, client_user
    ):
        issue_id = _send(client_api, anchor)
        _decide(session_client, workspace, project, issue_id, status=1)

        detail = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue_id}/").data

        assert detail["created_by_detail"]["email"] == client_user.email
        assert detail["created_by_detail"]["first_name"] == "Riya"


@pytest.mark.contract
class TestRoleLabels:
    """The Labels of the request form are the project's roles (its members' Project role), not its internal labels."""

    @pytest.mark.django_db
    def test_the_form_offers_the_members_roles_and_a_request_gets_their_label(
        self, session_client, workspace, project, anchor, client_api, create_user
    ):
        ProjectMember.objects.filter(project=project, member=create_user).update(designation="Project Manager")
        for email, designation in [
            ("flutter@example.com", "Flutter"),
            ("sf@example.com", "Salesforce Developer"),
            ("client@example.com", "Client"),
            ("react@example.com", "React JS"),
        ]:
            person = User.objects.create(email=email, username=email.split("@")[0])
            ProjectMember.objects.create(project=project, member=person, workspace=workspace, designation=designation)
        from plane.db.models import Label

        react = Label.objects.create(project=project, workspace=workspace, name="React JS", color="#123456")
        internal = Label.objects.create(project=project, workspace=workspace, name="Internal")

        form = client_api.get(PORTAL_URL.format(anchor=anchor)).data["forms"][0]
        choices = {choice["name"]: choice["id"] for choice in form["labels"]}
        response = client_api.post(
            f"{PORTAL_URL.format(anchor=anchor)}requests/",
            {
                "issue": {
                    "name": "Need a Salesforce sync",
                    "label_ids": [choices["Salesforce Developer"], choices["React JS"], str(internal.id)],
                }
            },
            format="json",
        )
        issue = Issue.objects.get(pk=response.data["issue_id"])

        # Client and Project Manager are not offered; a role with a label uses it, one without gets one later
        assert list(choices) == ["Flutter", "React JS", "Salesforce Developer"]
        assert choices["React JS"] == str(react.id)
        assert choices["Flutter"] == "role:Flutter"
        assert set(issue.labels.values_list("name", flat=True)) == {"Salesforce Developer", "React JS"}
        salesforce = Label.objects.get(project=project, name="Salesforce Developer")
        assert salesforce.parent.name == "Resource"
