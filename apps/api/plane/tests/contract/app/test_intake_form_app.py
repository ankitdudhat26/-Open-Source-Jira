# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The request form of a project's Intake: admins turn its link on, choose its fields and invite clients; invited
clients log in on the link to send requests and follow their status; declining a request needs a reason."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    FileAsset,
    Intake,
    IntakeFormInvite,
    IntakeIssue,
    Label,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)

FORM_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-form/"
INTAKE_ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-issues/"
PORTAL_URL = "/api/public/intake-forms/{anchor}/"


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        patch("plane.app.views.intake.base.issue_activity.delay"),
        patch("plane.app.views.intake.base.issue_description_version_task.delay"),
        patch("plane.space.views.intake_form.issue_activity.delay"),
        patch("plane.app.views.intake.form.intake_form_invitation.delay") as invitation,
    ):
        yield invitation


def _project(workspace, admin, name, identifier, intake=True):
    project = Project.objects.create(
        name=name, identifier=identifier, workspace=workspace, created_by=admin, intake_view=intake
    )
    ProjectMember.objects.create(project=project, member=admin, workspace=workspace, role=20)
    Intake.objects.create(name=f"{name} Intake", project=project, is_default=True)
    return project


@pytest.fixture
def project(db, workspace, create_user):
    return _project(workspace, create_user, "Customer App", "CA")


@pytest.fixture
def form_url(workspace, project):
    return FORM_URL.format(slug=workspace.slug, project_id=project.id)


@pytest.fixture
def client_user(db):
    """A client outside the workspace — they only know the form's link."""
    unique_id = uuid4().hex[:8]
    return User.objects.create(email=f"Client-{unique_id}@Example.com", username=f"client_{unique_id}")


@pytest.fixture
def client_api(client_user):
    api = APIClient()
    api.force_authenticate(user=client_user)
    return api


def _open_form(session_client, form_url, **changes):
    response = session_client.patch(form_url, {"is_enabled": True, **changes}, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data["anchor"]


def _invite(session_client, form_url, *emails):
    return session_client.post(f"{form_url}invites/", {"emails": list(emails)}, format="json")


def _send(api, anchor, **data):
    issue = {"name": "Login button does nothing", **data.pop("issue", {})}
    return api.post(f"{PORTAL_URL.format(anchor=anchor)}requests/", {"issue": issue, **data}, format="json")


@pytest.mark.contract
class TestIntakeFormSettings:
    @pytest.mark.django_db
    def test_link_is_off_and_every_field_on_by_default(self, session_client, form_url):
        response = session_client.get(form_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_enabled"] is False
        assert response.data["url"].endswith(f"/spaces/intake/{response.data['anchor']}")
        assert all(field["visible"] for field in response.data["fields"])

    @pytest.mark.django_db
    def test_admin_invites_clients_and_they_are_emailed_the_link(self, session_client, form_url, no_background_tasks):
        response = _invite(session_client, form_url, "Riya@Example.com", "riya@example.com", "dev@example.com")

        assert response.status_code == status.HTTP_200_OK, response.data
        assert [invite["email"] for invite in response.data] == ["dev@example.com", "riya@example.com"]
        assert no_background_tasks.call_count == 2
        assert "/spaces/intake/" in no_background_tasks.call_args.args[2]

    @pytest.mark.django_db
    def test_invalid_email_is_rejected(self, session_client, form_url):
        assert _invite(session_client, form_url, "not-an-email").status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_member_cannot_invite(self, workspace, project, form_url):
        unique_id = uuid4().hex[:8]
        member = User.objects.create(email=f"member-{unique_id}@example.com", username=f"member_{unique_id}")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        ProjectMember.objects.create(project=project, member=member, workspace=workspace, role=15)
        api = APIClient()
        api.force_authenticate(user=member)

        assert _invite(api, form_url, "x@example.com").status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
class TestClientPortal:
    @pytest.mark.django_db
    def test_link_asks_to_log_in_then_checks_the_invite(self, session_client, form_url, client_api, client_user):
        anchor = _open_form(session_client, form_url)
        url = PORTAL_URL.format(anchor=anchor)

        assert APIClient().get(url).data["access"] == "login"
        assert client_api.get(url).data["access"] == "not_invited"
        _invite(session_client, form_url, client_user.email.lower())
        assert client_api.get(url).data["access"] == "ok"

    @pytest.mark.django_db
    def test_link_off_shows_nothing(self, session_client, form_url, client_api, client_user):
        _invite(session_client, form_url, client_user.email)
        anchor = session_client.get(form_url).data["anchor"]

        assert client_api.get(PORTAL_URL.format(anchor=anchor)).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_client_gets_a_form_per_invited_project_by_its_settings(
        self, session_client, workspace, create_user, form_url, client_api, client_user
    ):
        other = _project(workspace, create_user, "Admin Panel", "AP")
        other_url = FORM_URL.format(slug=workspace.slug, project_id=other.id)
        _open_form(session_client, other_url, fields={"type": {"visible": False}, "labels": {"visible": False}})
        _invite(session_client, other_url, client_user.email)
        _project(workspace, create_user, "Not invited", "NI")
        anchor = _open_form(session_client, form_url)
        _invite(session_client, form_url, client_user.email)
        Label.objects.create(project=other, workspace=workspace, name="Hidden label")

        forms = client_api.get(PORTAL_URL.format(anchor=anchor)).data["forms"]

        assert [form["project_name"] for form in forms] == ["Customer App", "Admin Panel"]
        assert forms[0]["fields"] == ["title", "description", "type", "priority", "labels", "attachments"]
        assert forms[1]["fields"] == ["title", "description", "priority", "attachments"]
        assert forms[1]["labels"] == []

    @pytest.mark.django_db
    def test_client_sends_a_request_into_intake(self, session_client, form_url, client_api, client_user, project):
        anchor = _open_form(session_client, form_url, fields={"priority": {"visible": False}})
        _invite(session_client, form_url, client_user.email)

        response = _send(client_api, anchor, issue={"priority": "urgent", "description_html": "<p>On Android</p>"})

        assert response.status_code == status.HTTP_201_CREATED, response.data
        request = IntakeIssue.objects.get(project=project)
        assert (request.status, request.created_by_id, request.issue.state.group) == (-2, client_user.id, "triage")
        assert request.issue.priority == "none"
        assert "On Android" in request.issue.description_html

    @pytest.mark.django_db
    def test_uninvited_client_cannot_send(self, session_client, form_url, client_api, project):
        anchor = _open_form(session_client, form_url)

        assert _send(client_api, anchor).status_code == status.HTTP_404_NOT_FOUND
        assert not IntakeIssue.objects.filter(project=project).exists()

    @pytest.mark.django_db
    def test_client_sees_status_and_the_decline_reason(
        self, session_client, workspace, project, form_url, client_api, client_user
    ):
        anchor = _open_form(session_client, form_url)
        _invite(session_client, form_url, client_user.email)
        issue_id = _send(client_api, anchor).data["issue_id"]
        status_url = f"{INTAKE_ISSUES_URL.format(slug=workspace.slug, project_id=project.id)}{issue_id}/"

        without_reason = session_client.patch(status_url, {"status": -1}, format="json")
        declined = session_client.patch(
            status_url, {"status": -1, "decline_reason": "Not part of the agreed scope"}, format="json"
        )

        assert without_reason.status_code == status.HTTP_400_BAD_REQUEST
        assert declined.status_code == status.HTTP_200_OK, declined.data
        requests = client_api.get(f"{PORTAL_URL.format(anchor=anchor)}requests/").data
        assert [(r["key"], r["status_label"], r["decline_reason"]) for r in requests] == [
            ("CA-1", "Declined", "Not part of the agreed scope")
        ]

    @pytest.mark.django_db
    def test_client_attaches_a_file_to_their_request(self, session_client, form_url, client_api, client_user, project):
        anchor = _open_form(session_client, form_url)
        _invite(session_client, form_url, client_user.email)
        issue_id = _send(client_api, anchor).data["issue_id"]
        url = f"{PORTAL_URL.format(anchor=anchor)}requests/{issue_id}/attachments/"

        with patch("plane.space.views.intake_form.S3Storage.upload_file", return_value=True):
            response = client_api.post(
                url, {"file": SimpleUploadedFile("screen.png", b"\x89PNG data", content_type="image/png")}
            )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        asset = FileAsset.objects.get(issue_id=issue_id)
        assert (asset.is_uploaded, asset.attributes["name"]) == (True, "screen.png")

    @pytest.mark.django_db
    def test_no_attachments_when_the_form_has_them_off(self, session_client, form_url, client_api, client_user):
        anchor = _open_form(session_client, form_url, fields={"attachments": {"visible": False}})
        _invite(session_client, form_url, client_user.email)
        issue_id = _send(client_api, anchor).data["issue_id"]

        response = client_api.post(
            f"{PORTAL_URL.format(anchor=anchor)}requests/{issue_id}/attachments/",
            {"file": SimpleUploadedFile("screen.png", b"\x89PNG data", content_type="image/png")},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_removed_invite_closes_the_form(self, session_client, form_url, client_api, client_user):
        anchor = _open_form(session_client, form_url)
        invite_id = _invite(session_client, form_url, client_user.email).data[0]["id"]

        session_client.delete(f"{form_url}invites/{invite_id}/")

        assert client_api.get(PORTAL_URL.format(anchor=anchor)).data["access"] == "not_invited"
        assert not IntakeFormInvite.objects.filter(email__iexact=client_user.email).exists()
