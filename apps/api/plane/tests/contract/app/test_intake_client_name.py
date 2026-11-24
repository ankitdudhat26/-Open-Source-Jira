# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A client signs up on the Intake link with their full name; the team sees requests by it (not the email). A client
who signed up before the form asked for it is asked once on the portal."""

import uuid
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import User
from plane.license.models import Instance
from plane.utils.intake_portal import set_full_name

FORM_URL = "/api/workspaces/{slug}/projects/{project_id}/intake-form/"
PORTAL_URL = "/api/public/intake-forms/{anchor}/"


@pytest.fixture
def instance(db):
    instance_id = Instance.objects.first().id if Instance.objects.exists() else uuid.uuid4()
    Instance.objects.update_or_create(
        id=instance_id,
        defaults={
            "instance_name": "Test",
            "instance_id": str(uuid.uuid4()),
            "current_version": "1.0.0",
            "domain": "http://localhost:8000",
            "last_checked_at": timezone.now(),
            "is_setup_done": True,
        },
    )


@pytest.mark.contract
class TestClientName:
    @pytest.mark.django_db
    def test_sign_up_on_the_link_saves_the_full_name(self, instance, workspace, create_user):
        from plane.db.models import IntakeFormInvite, Project

        # only people invited to a request form (or a workspace) can sign up
        project = Project.objects.create(name="Zydus", identifier="ZYS", workspace=workspace, created_by=create_user)
        IntakeFormInvite.objects.create(project=project, workspace=workspace, email="tohoy@kranove.com")
        client = Client(HTTP_USER_AGENT="Mozilla/5.0")
        # logging in is not part of this test
        with patch("plane.authentication.views.space.email.user_login"):
            client.post(
                reverse("space-sign-up"),
                {
                    "email": "tohoy@kranove.com",
                    "password": "Str0ng!Passw0rd#2026",
                    "full_name": "  Manish   Kumar Singh ",
                },
            )

        user = User.objects.get(email="tohoy@kranove.com")
        assert (user.first_name, user.last_name) == ("Manish", "Kumar Singh")

    def test_a_single_word_is_the_first_name(self):
        user = User(email="a@b.c")
        with patch.object(User, "save"):
            assert set_full_name(user, "Manish") is True
            assert set_full_name(user, "   ") is False
        assert (user.first_name, user.last_name) == ("Manish", "")

    @pytest.mark.django_db
    def test_the_portal_asks_once_and_saves_the_name(self, session_client, workspace, create_user):
        from plane.db.models import Intake, Project, ProjectMember

        project = Project.objects.create(
            name="Zydus", identifier="ZYD", workspace=workspace, created_by=create_user, intake_view=True
        )
        ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
        Intake.objects.create(name="Intake", project=project, is_default=True)
        form_url = FORM_URL.format(slug=workspace.slug, project_id=project.id)
        anchor = session_client.patch(form_url, {"is_enabled": True}, format="json").data["anchor"]
        with patch("plane.app.views.intake.form.intake_form_invitation.delay"):
            session_client.post(f"{form_url}invites/", {"emails": ["info@gowell.com"]}, format="json")
        client_user = User.objects.create(email="info@gowell.com", username=f"info_{uuid.uuid4().hex[:6]}")
        api = APIClient()
        api.force_authenticate(user=client_user)
        portal = PORTAL_URL.format(anchor=anchor)

        assert (api.get(portal).data["full_name"], api.get(portal).data["needs_name"]) == ("", True)
        assert api.patch(f"{portal}me/", {"full_name": " "}, format="json").status_code == 400
        saved = api.patch(f"{portal}me/", {"full_name": "Hiren Desai"}, format="json")

        assert saved.status_code == 200 and saved.data["full_name"] == "Hiren Desai"
        assert (api.get(portal).data["full_name"], api.get(portal).data["needs_name"]) == ("Hiren Desai", False)
        # the team's Intake shows the request by that name
        request_id = api.post(f"{portal}requests/", {"issue": {"name": "Login fails"}}, format="json").data["issue_id"]
        detail = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/intake-issues/{request_id}/"
        ).data
        assert (detail["created_by_detail"]["first_name"], detail["created_by_detail"]["last_name"]) == (
            "Hiren",
            "Desai",
        )
