# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Invite a workspace member who cannot sign in yet (e.g. people added by the Jira import) by email."""

# Python imports
import logging
from urllib.parse import urlencode, urljoin

# Django imports
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import WorkspaceMemberAdminSerializer
from plane.app.views.base import BaseAPIView
from plane.authentication.views.app.password_management import InviteTokenGenerator, generate_invite_token
from plane.bgtasks.member_invite_email_task import send_member_invite_email
from plane.db.models import JiraEntityMap, Profile, User, WorkspaceMember
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.host import base_host

logger = logging.getLogger("plane.api")


class WorkspaceMemberSendInviteEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, pk):
        """Email the member a link to set a password; then they sign in with that email and password.

        A member without an email (a former Jira person) gets the email given here, and their account (with all
        their work items, comments and history) is switched on.
        """
        membership = (
            WorkspaceMember.objects.filter(workspace__slug=slug, pk=pk, is_active=True)
            .select_related("member", "workspace")
            .first()
        )
        if membership is None:
            return Response({"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND)
        user = membership.member
        if user.is_bot:
            return Response({"error": "Bots cannot sign in."}, status=status.HTTP_400_BAD_REQUEST)

        email = str(request.data.get("email") or user.email or "").strip().lower()
        if not email:
            return Response({"error": "Enter the member's email address."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_email(email)
        except ValidationError:
            return Response({"error": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
            return Response(
                {"error": f"{email} already belongs to another account. Use a different email."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not get_email_configuration()[0]:
            return Response(
                {"error": "Email is not set up. Configure the mail server in God mode → Email first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            user.email = email
            user.is_active = True
            user.is_email_verified = True
            user.save(update_fields=["email", "is_active", "is_email_verified", "updated_at"])
            Profile.objects.get_or_create(
                user=user,
                defaults={
                    "is_onboarded": True,
                    "last_workspace_id": membership.workspace_id,
                    "onboarding_step": {
                        "profile_complete": True,
                        "workspace_create": True,
                        "workspace_join": True,
                        "workspace_invite": True,
                    },
                },
            )
            # a former Jira person invited by hand: the next Jira user sync keeps the account on
            JiraEntityMap.objects.filter(
                workspace=membership.workspace, entity_type="user", plane_id=user.id, jira_updated="former"
            ).update(jira_updated="invited", jira_key=email)

        uidb64, token = generate_invite_token(user)
        app_url = base_host(request=request, is_app=True)
        invite_url = urljoin(
            app_url, "accounts/reset-password/?" + urlencode({"uidb64": uidb64, "token": token, "email": email})
        )
        try:
            send_member_invite_email(
                user,
                membership.workspace,
                request.user,
                invite_url,
                urljoin(app_url, "sign-in"),
                InviteTokenGenerator.VALID_DAYS,
            )
        except Exception as error:  # the admin is told; nothing is recorded as sent
            logger.exception("Member invite email to %s failed", email)
            return Response(
                {"error": f"The invite email could not be sent ({error}). Check the mail server settings."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        membership.invite_sent_at = timezone.now()
        membership.save(update_fields=["invite_sent_at", "updated_at"])
        membership.member.refresh_from_db()
        serializer = WorkspaceMemberAdminSerializer(
            membership, fields=("id", "member", "role", "company_role", "invite_sent_at")
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkspaceMemberDetailsEndpoint(BaseAPIView):
    NAME_FIELDS = ("first_name", "last_name", "display_name")

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, pk):
        """Edit a member's details: name and email while the account has never been signed in to (accounts the
        Jira import made), the job role always. People who sign in keep their own name and email (profile settings).
        """
        membership = (
            WorkspaceMember.objects.filter(workspace__slug=slug, pk=pk, is_active=True)
            .select_related("member", "workspace")
            .first()
        )
        if membership is None:
            return Response({"error": "Member not found."}, status=status.HTTP_404_NOT_FOUND)
        user = membership.member
        data = request.data
        user_changes = {}
        for field in self.NAME_FIELDS:
            if field in data:
                user_changes[field] = str(data.get(field) or "").strip()[:255]
        if "display_name" in user_changes and not user_changes["display_name"]:
            return Response({"error": "Display name cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
        if "email" in data:
            email = str(data.get("email") or "").strip().lower()
            if email != (user.email or ""):
                if not email:
                    return Response({"error": "Email cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    validate_email(email)
                except ValidationError:
                    return Response({"error": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)
                if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                    return Response(
                        {"error": f"{email} already belongs to another account."}, status=status.HTTP_400_BAD_REQUEST
                    )
                user_changes["email"] = email
        user_changes = {key: value for key, value in user_changes.items() if getattr(user, key) != value}
        if user_changes and (user.last_login is not None or not user.is_password_autoset or user == request.user):
            return Response(
                {"error": "This person signs in with their own account, so only they can change their name and email."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            if user_changes:
                for key, value in user_changes.items():
                    setattr(user, key, value)
                user.save(update_fields=[*user_changes, "updated_at"])
                if "email" in user_changes:
                    # the Jira user sync finds the person by this email from now on
                    JiraEntityMap.objects.filter(
                        workspace=membership.workspace, entity_type="user", plane_id=user.id
                    ).update(jira_key=user.email)
            if "company_role" in data:
                membership.company_role = str(data.get("company_role") or "").strip()[:255] or None
                membership.save(update_fields=["company_role", "updated_at"])
        serializer = WorkspaceMemberAdminSerializer(
            membership, fields=("id", "member", "role", "company_role", "invite_sent_at")
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
