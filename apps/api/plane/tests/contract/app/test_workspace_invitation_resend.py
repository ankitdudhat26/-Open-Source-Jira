# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace admins email a pending invitation again, e.g. when the first email never arrived."""

import uuid
from unittest import mock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import User, WorkspaceMember, WorkspaceMemberInvite


def _url(workspace, invitation):
    return f"/api/workspaces/{workspace.slug}/invitations/{invitation.id}/resend/"


@pytest.fixture
def invitation(db, workspace):
    return WorkspaceMemberInvite.objects.create(
        workspace=workspace, email="nikhil@example.com", token="invite-token", role=15, designation="Designer"
    )


@pytest.mark.contract
class TestWorkspaceInvitationResend:
    @pytest.mark.django_db
    def test_admin_resends_a_pending_invitation(self, session_client, workspace, invitation):
        with mock.patch("plane.app.views.workspace.invite.workspace_invitation.delay") as send:
            response = session_client.post(_url(workspace, invitation))

        assert response.status_code == status.HTTP_200_OK, response.data
        send.assert_called_once()
        assert send.call_args.args[:3] == ("nikhil@example.com", workspace.id, "invite-token")

    @pytest.mark.django_db
    def test_no_email_once_they_have_joined(self, session_client, workspace, invitation):
        user = User.objects.create(email="nikhil@example.com", username=uuid.uuid4().hex)
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)

        with mock.patch("plane.app.views.workspace.invite.workspace_invitation.delay") as send:
            response = session_client.post(_url(workspace, invitation))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        send.assert_not_called()

    @pytest.mark.django_db
    def test_members_cannot_resend(self, workspace, invitation):
        user = User.objects.create(email=f"{uuid.uuid4().hex}@example.com", username=uuid.uuid4().hex)
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        api = APIClient()
        api.force_authenticate(user=user)

        with mock.patch("plane.app.views.workspace.invite.workspace_invitation.delay") as send:
            response = api.post(_url(workspace, invitation))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        send.assert_not_called()
