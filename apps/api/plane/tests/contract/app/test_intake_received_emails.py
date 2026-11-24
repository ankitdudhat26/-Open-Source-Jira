# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Intake received emails: in Settings → Intake a project admin switches on the members who are emailed when a client
sends a request on the Intake link. Nobody is switched on by default."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.bgtasks.intake_request_status_task import intake_request_received
from plane.db.models import Intake, IntakeIssue, Project, ProjectMember, User, WorkspaceMember

FORM_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-form/"
PORTAL_URL = "/api/public/intake-forms/{anchor}/"


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        patch("plane.space.views.intake_form.issue_activity.delay"),
        patch("plane.app.views.intake.form.intake_form_invitation.delay"),
    ):
        yield


def _person(workspace, project, name, role=15):
    user = User.objects.create(
        email=f"{name}-{uuid4().hex[:6]}@example.com", username=f"{name}_{uuid4().hex[:6]}", first_name=name.title()
    )
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


@pytest.fixture
def setup(db, workspace, create_user, session_client):
    project = Project.objects.create(
        name="Zydus DMS Support", identifier="ZDS", workspace=workspace, created_by=create_user, intake_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    Intake.objects.create(name="Intake", project=project, is_default=True)
    rajendra, keval = _person(workspace, project, "rajendra"), _person(workspace, project, "keval")
    client = User.objects.create(email=f"client-{uuid4().hex[:6]}@example.com", username=f"client_{uuid4().hex[:6]}")
    form_url = FORM_URL.format(slug=workspace.slug, project_id=project.id)
    anchor = session_client.patch(form_url, {"is_enabled": True}, format="json").data["anchor"]
    session_client.post(f"{form_url}invites/", {"emails": [client.email]}, format="json")
    client_api = APIClient()
    client_api.force_authenticate(user=client)
    return project, form_url, anchor, rajendra, keval, client, client_api


@pytest.mark.contract
class TestIntakeReceivedEmails:
    @pytest.mark.django_db
    def test_nobody_is_emailed_by_default_and_admins_choose_members(self, session_client, workspace, setup):
        project, form_url, _, rajendra, keval, _, _ = setup

        assert session_client.get(form_url).data["notify_member_ids"] == []
        saved = session_client.patch(form_url, {"notify_member_ids": [str(rajendra.id)]}, format="json")
        outsider = User.objects.create(email="out@example.com", username=f"out_{uuid4().hex[:6]}")
        refused = session_client.patch(form_url, {"notify_member_ids": [str(outsider.id)]}, format="json")
        member_api = APIClient()
        member_api.force_authenticate(user=keval)
        not_admin = member_api.patch(form_url, {"notify_member_ids": [str(keval.id)]}, format="json")

        assert saved.status_code == status.HTTP_200_OK, saved.data
        assert saved.data["notify_member_ids"] == [str(rajendra.id)]
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert not_admin.status_code == status.HTTP_403_FORBIDDEN
        # a member who leaves the project is no longer listed (nor emailed)
        ProjectMember.objects.filter(project=project, member=rajendra).update(is_active=False)
        assert session_client.get(form_url).data["notify_member_ids"] == []

    @pytest.mark.django_db
    def test_a_client_request_emails_the_switched_on_members(
        self, session_client, workspace, setup, django_capture_on_commit_callbacks
    ):
        project, form_url, anchor, rajendra, keval, client, client_api = setup
        session_client.patch(form_url, {"notify_member_ids": [str(rajendra.id)]}, format="json")

        with patch("plane.space.views.intake_form.intake_request_received.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                response = client_api.post(
                    f"{PORTAL_URL.format(anchor=anchor)}requests/",
                    {
                        "issue": {
                            "name": "E-mail notification for transactions",
                            "description_html": "<p>No emails are received by Shine.</p>",
                            "priority": "high",
                        }
                    },
                    format="json",
                )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        intake_issue_id, app_url = delay.call_args.args
        assert intake_issue_id == response.data["id"]

        with patch("plane.bgtasks.intake_request_status_task._send") as send:
            intake_request_received(intake_issue_id, app_url)

        assert [call.args[1] for call in send.call_args_list] == [rajendra.email]
        subject, _, html = send.call_args.args
        issue = IntakeIssue.objects.get(pk=intake_issue_id).issue
        assert subject == f"New intake request ZDS-{issue.sequence_id} — Zydus DMS Support"
        assert "E-mail notification for transactions" in html
        assert "No emails are received by Shine." in html
        assert client.email in html
        assert "High" in html
        assert f"/{workspace.slug}/projects/{project.id}/intake?currentTab=open&amp;inboxIssueId={issue.id}" in html

    @pytest.mark.django_db
    def test_no_email_when_nobody_is_switched_on(self, session_client, setup):
        _, _, anchor, _, _, _, client_api = setup
        response = client_api.post(
            f"{PORTAL_URL.format(anchor=anchor)}requests/", {"issue": {"name": "Login fails"}}, format="json"
        )

        with patch("plane.bgtasks.intake_request_status_task._send") as send:
            intake_request_received(response.data["id"], "http://app.test")

        send.assert_not_called()
