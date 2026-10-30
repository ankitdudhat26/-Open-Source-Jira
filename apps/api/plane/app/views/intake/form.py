# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Count
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from ..base import BaseAPIView
from plane.app.permissions import allow_permission, ROLE
from plane.bgtasks.intake_form_invitation_task import intake_form_invitation
from plane.db.models import IntakeFormInvite, IntakeIssue, Project, User
from plane.db.models.intake import get_form_anchor
from plane.utils.host import base_host
from plane.utils.intake_form import IntakeFormError, form_fields, get_form, open_form_filter, save_form_fields
from plane.utils.project_membership import is_project_client

MAX_INVITES_PER_REQUEST = 50


def form_url(request, form):
    return f"{base_host(request=request, is_space=True)}intake/{form.anchor}"


def _form_data(request, form):
    return {
        "anchor": form.anchor,
        "url": form_url(request, form),
        "is_enabled": form.is_enabled,
        "fields": form_fields(form.project_id),
    }


def _invites_data(project_id):
    invites = list(IntakeFormInvite.objects.filter(project_id=project_id).order_by("email"))
    emails = [invite.email.lower() for invite in invites]
    users = {user.email.lower(): user for user in User.objects.filter(email__in=emails)} if emails else {}
    request_counts = dict(
        IntakeIssue.objects.filter(project_id=project_id, created_by__in=list(users.values()))
        .values("created_by_id")
        .annotate(count=Count("id"))
        .values_list("created_by_id", "count")
    )
    data = []
    for invite in invites:
        user = users.get(invite.email.lower())
        data.append(
            {
                "id": str(invite.id),
                "email": invite.email,
                "name": (user.display_name if user else "") or "",
                "has_account": bool(user),
                "request_count": request_counts.get(user.id, 0) if user else 0,
                "last_sent_at": invite.last_sent_at,
                "created_at": invite.created_at,
            }
        )
    return data


class IntakeFormEndpoint(BaseAPIView):
    """The request form of the project's Intake: its link (on/off), and which fields it shows. Members read it (their
    own Intake dialog follows the fields), clients get just its link; project admins change it."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        if is_project_client(request.user, slug, project_id):
            # a client only needs the link (they send requests there, logged in as they are here) — while it is open
            is_open = Project.objects.filter(open_form_filter(), pk=project.pk).exists()
            form = get_form(project) if is_open else None
            return Response(
                {"is_enabled": is_open, "url": form_url(request, form) if form else None}, status=status.HTTP_200_OK
            )
        return Response(_form_data(request, get_form(project)), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        form = get_form(project)
        if "is_enabled" in request.data:
            is_enabled = bool(request.data.get("is_enabled"))
            if is_enabled and not project.intake_view:
                return Response({"error": "Turn on Intake for this project first."}, status=status.HTTP_400_BAD_REQUEST)
            form.is_enabled = is_enabled
        if "fields" in request.data:
            try:
                save_form_fields(form, request.data.get("fields"))
            except IntakeFormError as error:
                return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        form.save()
        return Response(_form_data(request, form), status=status.HTTP_200_OK)


class IntakeFormResetLinkEndpoint(BaseAPIView):
    """A new link for the form; the old one stops working. Invited clients get the new link when invited again."""

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        form = get_form(project)
        form.anchor = get_form_anchor()
        form.save(update_fields=["anchor", "updated_at"])
        return Response(_form_data(request, form), status=status.HTTP_200_OK)


class IntakeFormInviteEndpoint(BaseAPIView):
    """The clients invited to the project's request form. Inviting emails them the link; they log in there with that
    email to send requests and follow them. Inviting someone already invited sends the email again."""

    @allow_permission([ROLE.ADMIN])
    def get(self, request, slug, project_id):
        return Response(_invites_data(project_id), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        emails = request.data.get("emails")
        if not isinstance(emails, list) or not emails:
            return Response({"error": "Enter at least one email address."}, status=status.HTTP_400_BAD_REQUEST)
        if len(emails) > MAX_INVITES_PER_REQUEST:
            return Response(
                {"error": f"Invite at most {MAX_INVITES_PER_REQUEST} people at a time."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cleaned = []
        for raw in emails:
            email = str(raw or "").strip().lower()
            try:
                validate_email(email)
            except ValidationError:
                return Response({"error": f"{raw} is not a valid email address."}, status=status.HTTP_400_BAD_REQUEST)
            if email not in cleaned:
                cleaned.append(email)
        if not project.intake_view:
            return Response({"error": "Turn on Intake for this project first."}, status=status.HTTP_400_BAD_REQUEST)

        # off: the clients are added without an email — the admin shares the link with them another way
        send_email = request.data.get("send_email", True) is not False

        form = get_form(project)
        url = form_url(request, form)
        sent_at = timezone.now() if send_email else None
        for email in cleaned:
            invite = IntakeFormInvite.objects.filter(project=project, email__iexact=email).first()
            if not invite:
                IntakeFormInvite.objects.create(project=project, email=email, last_sent_at=sent_at)
            elif send_email:
                invite.last_sent_at = sent_at
                invite.save(update_fields=["last_sent_at", "updated_at"])
            if send_email:
                intake_form_invitation.delay(email, str(project.id), url, str(request.user.id))
        return Response(_invites_data(project_id), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        invite = IntakeFormInvite.objects.filter(project_id=project_id, pk=pk).first()
        if invite:
            invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
