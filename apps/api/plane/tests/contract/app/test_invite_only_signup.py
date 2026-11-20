# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Sign up is by invitation only: no account without an admin's invitation to that email, by any way of signing up."""

import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from plane.authentication.utils.user_auth_workflow import post_user_auth_workflow
from plane.db.models import Profile, User, WorkspaceMember, WorkspaceMemberInvite
from plane.license.models import Instance

STRONG_PASSWORD = "Correct-Horse-Battery-42!"
SIGNUP_DISABLED = "5015"


@pytest.fixture
def instance(db):
    instance = Instance.objects.first() or Instance(id=uuid.uuid4())
    instance.instance_name, instance.instance_id = "Test", str(uuid.uuid4())
    instance.current_version, instance.last_checked_at, instance.is_setup_done = "1.0.0", timezone.now(), True
    instance.save()
    return instance


@pytest.fixture
def browser():
    return Client(HTTP_USER_AGENT="Mozilla/5.0")


@pytest.fixture(autouse=True)
def anyone_may_sign_up_says_the_instance(settings, monkeypatch):
    # the old instance switch ("allow anyone to sign up") no longer opens sign up
    monkeypatch.setenv("ENABLE_SIGNUP", "1")


def invite(workspace, email):
    return WorkspaceMemberInvite.objects.create(workspace=workspace, email=email, role=15, token=uuid.uuid4().hex)


def error_code(response):
    return parse_qs(urlparse(response.url).query).get("error_code", [None])[0]


@pytest.mark.contract
class TestInviteOnlySignup:
    @pytest.mark.django_db
    def test_password_sign_up_without_invitation_is_refused(self, browser, instance):
        response = browser.post(reverse("sign-up"), {"email": "stranger@example.com", "password": STRONG_PASSWORD})

        assert response.status_code == status.HTTP_302_FOUND
        assert error_code(response) == SIGNUP_DISABLED
        assert not User.objects.filter(email="stranger@example.com").exists()

    @pytest.mark.django_db
    def test_invited_email_signs_up_with_a_password(self, browser, instance, workspace):
        invite(workspace, "Invited@Example.com")

        response = browser.post(reverse("sign-up"), {"email": "invited@example.com", "password": STRONG_PASSWORD})

        assert response.status_code == status.HTTP_302_FOUND
        assert error_code(response) is None
        user = User.objects.get(email="invited@example.com")
        # a password does not prove the mailbox: the invitation is accepted from the email's link
        assert not user.is_email_verified
        assert not WorkspaceMember.objects.filter(member=user).exists()

    @pytest.mark.django_db
    def test_email_check_tells_an_uninvited_email_it_cannot_sign_up(self, browser, instance, workspace, create_user):
        url = "/auth/email-check/"
        refused = browser.post(url, {"email": "stranger@example.com"}, content_type="application/json")
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert str(refused.json()["error_code"]) == SIGNUP_DISABLED

        invite(workspace, "invited@example.com")
        assert (
            browser.post(url, {"email": "invited@example.com"}, content_type="application/json").json()["existing"]
            is False
        )
        # people with an account sign in as before
        assert browser.post(url, {"email": create_user.email}, content_type="application/json").json()["existing"]

    @pytest.mark.django_db
    @patch("plane.authentication.views.app.magic.magic_link.delay")
    def test_no_magic_code_is_sent_to_an_uninvited_email(self, send, browser, instance):
        response = browser.post(
            reverse("magic-generate"), {"email": "stranger@example.com"}, content_type="application/json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert str(response.json()["error_code"]) == SIGNUP_DISABLED
        send.assert_not_called()

    @pytest.mark.django_db
    def test_the_instance_hides_the_sign_up_link(self, api_client, instance):
        assert api_client.get("/api/instances/").data["config"]["enable_signup"] is False

    @pytest.mark.django_db
    def test_signing_up_does_not_join_a_workspace_on_its_own(self, workspace):
        user = User.objects.create(email="invited@example.com", username=uuid.uuid4().hex)
        Profile.objects.create(user=user)
        invite(workspace, "invited@example.com")

        post_user_auth_workflow(user, True, None)

        # the invitation is theirs to accept (onboarding lists it)
        assert not WorkspaceMember.objects.filter(member=user).exists()


@pytest.mark.contract
class TestJoiningNeedsTheEmail:
    @pytest.mark.django_db
    def test_a_password_sign_up_joins_with_the_emailed_link_not_the_list(self, api_client, workspace):
        user = User.objects.create(email="invited@example.com", username=uuid.uuid4().hex, is_email_verified=False)
        invitation = invite(workspace, "invited@example.com")
        api_client.force_authenticate(user=user)

        listed = api_client.post(
            "/api/users/me/workspaces/invitations/", {"invitations": [str(invitation.id)]}, format="json"
        )
        assert listed.status_code == status.HTTP_403_FORBIDDEN
        assert not WorkspaceMember.objects.filter(member=user).exists()

        joined = api_client.post(
            f"/api/workspaces/{workspace.slug}/invitations/{invitation.id}/join/",
            {"accepted": True, "token": invitation.token},
            format="json",
        )
        assert joined.status_code == status.HTTP_200_OK, joined.data
        assert WorkspaceMember.objects.filter(member=user, workspace=workspace).exists()
        assert User.objects.get(pk=user.pk).is_email_verified

    @pytest.mark.django_db
    def test_a_verified_email_joins_from_the_list(self, api_client, workspace):
        user = User.objects.create(email="invited@example.com", username=uuid.uuid4().hex, is_email_verified=True)
        invitation = invite(workspace, "invited@example.com")
        api_client.force_authenticate(user=user)

        response = api_client.post(
            "/api/users/me/workspaces/invitations/", {"invitations": [str(invitation.id)]}, format="json"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert WorkspaceMember.objects.filter(member=user, workspace=workspace).exists()
