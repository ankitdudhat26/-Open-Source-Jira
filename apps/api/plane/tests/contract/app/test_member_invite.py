# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Inviting workspace members who cannot sign in yet (e.g. accounts made by the Jira import) by email."""

import html as html_lib
import re
import uuid
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.test import Client
from rest_framework import status

from plane.authentication.views.app.password_management import InviteTokenGenerator
from plane.db.models import JiraEntityMap, Profile, User, WorkspaceMember

MAIL_SETTINGS = ("smtp.example.com", "", "", "587", "1", "0", "Hlink Sprint <no-reply@example.com>")
STRONG_PASSWORD = "Correct-Horse-Battery-42!"


def member(workspace, **fields):
    defaults = {"username": uuid.uuid4().hex, "first_name": "Ravi", "display_name": "Ravi", "is_password_autoset": True}
    user = User(**{**defaults, **fields})
    user.set_unusable_password()
    user.save()
    return WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)


@pytest.fixture
def mail_server():
    with (
        mock.patch("plane.app.views.workspace.member_invite.get_email_configuration", return_value=MAIL_SETTINGS),
        mock.patch("plane.bgtasks.member_invite_email_task.get_email_configuration", return_value=MAIL_SETTINGS),
        mock.patch("plane.bgtasks.member_invite_email_task.get_connection", return_value=mail.get_connection()),
    ):
        yield


def invite_link(message):
    html = message.alternatives[0][0]
    url = html_lib.unescape(re.search(r'href="([^"]*reset-password[^"]*)"', html).group(1))
    query = parse_qs(urlparse(url).query)
    return query["uidb64"][0], query["token"][0]


@pytest.mark.contract
class TestMemberInvite:
    @pytest.mark.django_db
    def test_invited_member_sets_a_password_and_signs_in_with_the_same_email(
        self, session_client, workspace, mail_server, settings
    ):
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        membership = member(workspace, email="ravi@example.com")
        members = session_client.get(f"/api/workspaces/{workspace.slug}/members/").data
        assert next(m for m in members if str(m["id"]) == str(membership.id))["member"]["access_status"] == "pending"

        response = session_client.post(f"/api/workspaces/{workspace.slug}/members/{membership.id}/send-invite/")

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["invite_sent_at"] and response.data["member"]["email"] == "ravi@example.com"
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["ravi@example.com"]
        assert "Test Workspace" in mail.outbox[0].subject

        # the link in the email sets the password (it is valid for days, unlike a forgot password link)
        uidb64, token = invite_link(mail.outbox[0])
        user = membership.member
        with mock.patch.object(
            InviteTokenGenerator, "_now", return_value=InviteTokenGenerator()._now() + timedelta(days=6)
        ):
            done = Client().post(f"/auth/reset-password/{uidb64}/{token}/", {"password": STRONG_PASSWORD})
        assert done.status_code == 302 and "sign-in?success=True" in done["Location"]
        user.refresh_from_db()
        assert user.check_password(STRONG_PASSWORD) and not user.is_password_autoset

        # the link works once
        again = Client().post(f"/auth/reset-password/{uidb64}/{token}/", {"password": "Another-Strong-Pass-77!"})
        assert "INVALID_PASSWORD_TOKEN" in again["Location"] or "error_code" in again["Location"]

    @pytest.mark.django_db
    def test_expired_invite_link_is_refused(self, session_client, workspace, mail_server, settings):
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        membership = member(workspace, email="ravi@example.com")
        session_client.post(f"/api/workspaces/{workspace.slug}/members/{membership.id}/send-invite/")
        uidb64, token = invite_link(mail.outbox[0])
        with mock.patch.object(
            InviteTokenGenerator, "_now", return_value=InviteTokenGenerator()._now() + timedelta(days=8)
        ):
            refused = Client().post(f"/auth/reset-password/{uidb64}/{token}/", {"password": STRONG_PASSWORD})
        assert "reset-password" in refused["Location"]
        membership.member.refresh_from_db()
        assert not membership.member.check_password(STRONG_PASSWORD)

    @pytest.mark.django_db
    def test_former_jira_person_gets_the_email_given_and_can_sign_in(
        self, session_client, workspace, mail_server, settings
    ):
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        membership = member(workspace, email=None, is_active=False)
        JiraEntityMap.objects.create(
            workspace=workspace,
            entity_type="user",
            jira_id="acc-1",
            plane_id=membership.member_id,
            jira_updated="former",
        )
        url = f"/api/workspaces/{workspace.slug}/members/{membership.id}/send-invite/"
        assert session_client.post(url).status_code == status.HTTP_400_BAD_REQUEST  # no email yet
        assert session_client.post(url, {"email": "test@plane.so"}, format="json").status_code == 400  # taken

        response = session_client.post(url, {"email": " Ravi.Shah@Example.com "}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["member"]["access_status"] == "pending"
        user = User.objects.get(pk=membership.member_id)
        assert (user.email, user.is_active, user.is_email_verified) == ("ravi.shah@example.com", True, True)
        assert Profile.objects.filter(user=user, is_onboarded=True).exists()
        assert JiraEntityMap.objects.get(jira_id="acc-1").jira_updated == "invited"
        assert mail.outbox[0].to == ["ravi.shah@example.com"]

    @pytest.mark.django_db
    def test_nothing_is_marked_sent_when_mail_fails_or_is_not_set_up(self, session_client, workspace, settings):
        membership = member(workspace, email="ravi@example.com")
        url = f"/api/workspaces/{workspace.slug}/members/{membership.id}/send-invite/"
        with mock.patch(
            "plane.app.views.workspace.member_invite.get_email_configuration", return_value=("", *MAIL_SETTINGS[1:])
        ):
            response = session_client.post(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST and "God mode" in response.data["error"]

        with (
            mock.patch("plane.app.views.workspace.member_invite.get_email_configuration", return_value=MAIL_SETTINGS),
            mock.patch(
                "plane.app.views.workspace.member_invite.send_member_invite_email",
                side_effect=OSError("connection refused"),
            ),
        ):
            response = session_client.post(url)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY and "connection refused" in response.data["error"]
        membership.refresh_from_db()
        assert membership.invite_sent_at is None

    @pytest.mark.django_db
    def test_only_admins_invite(self, api_client, workspace, mail_server):
        membership = member(workspace, email="ravi@example.com")
        other = member(workspace, email="mira@example.com")
        api_client.force_authenticate(user=other.member)
        response = api_client.post(f"/api/workspaces/{workspace.slug}/members/{membership.id}/send-invite/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_jira_user_sync_keeps_an_invited_person_on(self, workspace, create_user):
        from plane.db.models import JiraSyncRun
        from plane.utils.jira.importer import JiraImporter

        membership = member(workspace, email="ravi@example.com")
        mapped = JiraEntityMap.objects.create(
            workspace=workspace,
            entity_type="user",
            jira_id="acc-1",
            plane_id=membership.member_id,
            jira_updated="invited",
        )
        run = JiraSyncRun.objects.create(workspace=workspace, initiated_by=create_user, options={"kind": "users"})
        # still deactivated in Jira: the admin's invite wins
        JiraImporter(run, mock.Mock(), workspace, create_user).deactivate_user(mapped, {"accountId": "acc-1"})
        membership.refresh_from_db()
        assert membership.is_active and User.objects.get(pk=membership.member_id).is_active


@pytest.mark.contract
class TestMemberDetailsEdit:
    @pytest.mark.django_db
    def test_admin_edits_a_member_who_never_signed_in(self, session_client, workspace):
        membership = member(workspace, email=None, is_active=False)
        JiraEntityMap.objects.create(
            workspace=workspace,
            entity_type="user",
            jira_id="acc-1",
            plane_id=membership.member_id,
            jira_updated="former",
        )
        url = f"/api/workspaces/{workspace.slug}/members/{membership.id}/details/"
        response = session_client.patch(
            url,
            {
                "first_name": "Ravi",
                "last_name": "Shah",
                "display_name": "Ravi Shah",
                "email": "Ravi@Example.com",
                "company_role": "Developer",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        user = User.objects.get(pk=membership.member_id)
        assert (user.first_name, user.last_name, user.display_name, user.email) == (
            "Ravi",
            "Shah",
            "Ravi Shah",
            "ravi@example.com",
        )
        assert response.data["company_role"] == "Developer"
        assert JiraEntityMap.objects.get(jira_id="acc-1").jira_key == "ravi@example.com"

        assert session_client.patch(url, {"display_name": " "}, format="json").status_code == 400
        assert session_client.patch(url, {"email": "test@plane.so"}, format="json").status_code == 400  # taken
        assert session_client.patch(url, {"email": "not-an-email"}, format="json").status_code == 400

    @pytest.mark.django_db
    def test_people_who_sign_in_keep_their_own_name_and_email(self, session_client, workspace):
        membership = member(workspace, email="mira@example.com", is_password_autoset=False)
        url = f"/api/workspaces/{workspace.slug}/members/{membership.id}/details/"

        refused = session_client.patch(url, {"display_name": "Someone else"}, format="json")
        assert refused.status_code == status.HTTP_403_FORBIDDEN
        # the job role is the workspace's, so it can always be set (unchanged names are fine to send along)
        response = session_client.patch(
            url, {"display_name": "Ravi", "email": "mira@example.com", "company_role": "Designer"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert WorkspaceMember.objects.get(pk=membership.pk).company_role == "Designer"
        assert User.objects.get(pk=membership.member_id).display_name == "Ravi"

    @pytest.mark.django_db
    def test_only_admins_edit(self, api_client, workspace):
        membership = member(workspace, email="ravi@example.com")
        other = member(workspace, email="mira@example.com")
        api_client.force_authenticate(user=other.member)
        response = api_client.patch(
            f"/api/workspaces/{workspace.slug}/members/{membership.id}/details/", {"display_name": "X"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
