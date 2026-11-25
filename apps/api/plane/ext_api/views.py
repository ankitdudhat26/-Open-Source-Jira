# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib
import os

# Django imports
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from plane.db.models import ExternalApiSession, Issue, ProjectMember, User, WorkspaceMember
from plane.db.models.external_api import hash_token, new_token, password_fingerprint
from plane.license.utils.instance_value import get_configuration_value
from plane.settings.storage import S3Storage
from plane.utils.uuid import is_valid_uuid

from .authentication import (
    ACCOUNT_FAILURE_LIMIT,
    ACCOUNT_FAILURE_WINDOW,
    SESSION_LIFETIME,
    ExternalApiAuthentication,
    ExternalApiRateThrottle,
    LoginRateThrottle,
    client_ip,
)
from .serializers import project_row, user_brief, work_item_detail, work_item_row, work_items_queryset

GUEST = 5
DEFAULT_PER_PAGE = 100
MAX_PER_PAGE = 500


def error(message, code, http_status):
    return Response({"error": message, "code": code}, status=http_status)


def memberships(user):
    """The user's active memberships of live projects (not archived or deleted) in workspaces they still belong to —
    the projects of My Projects."""
    in_workspace = WorkspaceMember.objects.filter(
        workspace_id=OuterRef("project__workspace_id"), member_id=OuterRef("member_id"), is_active=True
    )
    return ProjectMember.objects.filter(
        member=user,
        is_active=True,
        project__deleted_at__isnull=True,
        project__archived_at__isnull=True,
        project__workspace__deleted_at__isnull=True,
    ).filter(Exists(in_workspace))


def membership_for(user, project_id):
    if not is_valid_uuid(str(project_id)):
        return None
    return memberships(user).select_related("project", "project__workspace").filter(project_id=project_id).first()


def visible_work_items(membership):
    """A project's work items this member may see: a guest of a project that hides the rest sees only their own."""
    items = work_items_queryset(membership.project)
    if membership.role == GUEST and not membership.project.guest_view_all_features:
        items = items.filter(created_by=membership.member)
    return items


class ExternalApiView(APIView):
    authentication_classes = [ExternalApiAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ExternalApiRateThrottle]


class LoginEndpoint(APIView):
    """POST {email, password} → a Bearer token for the other endpoints."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        # the instance's "password sign-in" switch (God mode → Authentication) applies here too
        (password_login,) = get_configuration_value(
            [{"key": "ENABLE_EMAIL_PASSWORD", "default": os.environ.get("ENABLE_EMAIL_PASSWORD", "1")}]
        )
        if password_login == "0":
            return error(
                "Password sign-in is turned off on this instance.", "PASSWORD_LOGIN_DISABLED", status.HTTP_403_FORBIDDEN
            )
        email = str(request.data.get("email") or "").strip().lower()
        password = str(request.data.get("password") or "")
        if not email or not password:
            return error("Send email and password.", "MISSING_CREDENTIALS", status.HTTP_400_BAD_REQUEST)
        try:
            validate_email(email)
        except ValidationError:
            return error("Enter a valid email.", "INVALID_EMAIL", status.HTTP_400_BAD_REQUEST)
        # too many wrong passwords for this account recently (whatever addresses they came from)
        failures_key = f"ext_api_login_fail:{hashlib.sha256(email.encode()).hexdigest()}"
        if (cache.get(failures_key) or 0) >= ACCOUNT_FAILURE_LIMIT:
            return error(
                "Too many failed logins for this account. Try again in 15 minutes.",
                "TOO_MANY_FAILED_LOGINS",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        user = User.objects.filter(email=email).first()
        eligible = user is not None and user.is_active and not user.is_bot and user.has_usable_password()
        if eligible:
            valid = user.check_password(password)
        else:
            # hash anyway, so an unknown email takes as long to answer as a wrong password
            make_password(password)
            valid = False
        # one answer for an unknown email and a wrong password, so emails cannot be guessed
        if not valid:
            try:
                cache.add(failures_key, 0, ACCOUNT_FAILURE_WINDOW)
                cache.incr(failures_key)
            except ValueError:
                cache.set(failures_key, 1, ACCOUNT_FAILURE_WINDOW)
            return error("Email or password is incorrect.", "INVALID_CREDENTIALS", status.HTTP_401_UNAUTHORIZED)
        cache.delete(failures_key)
        token = new_token()
        session = ExternalApiSession.objects.create(
            user=user,
            token_hash=hash_token(token),
            token_hint=token[:12],
            password_fingerprint=password_fingerprint(user),
            expires_at=timezone.now() + SESSION_LIFETIME,
            user_agent=(request.headers.get("User-Agent") or "")[:512],
            ip_address=client_ip(request),
        )
        return Response(
            {
                "token": token,
                "token_type": "Bearer",
                "expires_at": session.expires_at.isoformat(),
                "user": user_brief(user),
            },
            status=status.HTTP_200_OK,
        )


class LogoutEndpoint(ExternalApiView):
    """POST → the token used for this request stops working."""

    def post(self, request):
        ExternalApiSession.objects.filter(pk=request.auth.pk).update(revoked_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeEndpoint(ExternalApiView):
    """GET → who the token belongs to."""

    def get(self, request):
        return Response(user_brief(request.user), status=status.HTTP_200_OK)


class ProjectListEndpoint(ExternalApiView):
    """GET → the projects the user is a member of (My Projects), by name."""

    def get(self, request):
        rows = (
            memberships(request.user)
            .select_related("project", "project__workspace", "project__project_lead")
            .order_by("project__name")
        )
        workspace = request.query_params.get("workspace")
        if workspace:
            rows = rows.filter(project__workspace__slug=workspace)
        search = (request.query_params.get("search") or "").strip()
        if search:
            rows = rows.filter(Q(project__name__icontains=search) | Q(project__identifier__icontains=search))
        projects = [project_row(row.project, row.role) for row in rows]
        return Response({"count": len(projects), "results": projects}, status=status.HTTP_200_OK)


class ProjectWorkItemListEndpoint(ExternalApiView):
    """GET → every work item of a project (every status), newest first, a page at a time."""

    def get(self, request, project_id):
        membership = membership_for(request.user, project_id)
        if membership is None:
            return error("Project not found.", "PROJECT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            per_page = min(MAX_PER_PAGE, max(1, int(request.query_params.get("per_page", DEFAULT_PER_PAGE))))
        except ValueError:
            return error("page and per_page must be numbers.", "INVALID_PAGINATION", status.HTTP_400_BAD_REQUEST)

        items = visible_work_items(membership)
        filters = {
            "state_group": "state__group__in",
            "priority": "priority__in",
        }
        for param, lookup in filters.items():
            values = [value for value in (request.query_params.get(param) or "").split(",") if value]
            if values:
                items = items.filter(**{lookup: values})
        state_ids = [value for value in (request.query_params.get("state_id") or "").split(",") if is_valid_uuid(value)]
        if state_ids:
            items = items.filter(state_id__in=state_ids)
        search = (request.query_params.get("search") or "").strip()
        if search:
            match = Q(name__icontains=search)
            if search.isdigit():
                match |= Q(sequence_id=int(search))
            items = items.filter(match)

        total = items.count()
        start = (page - 1) * per_page
        rows = [work_item_row(issue) for issue in items.order_by("-created_at")[start : start + per_page]]
        total_pages = (total + per_page - 1) // per_page
        return Response(
            {
                "project": {"id": str(membership.project.id), "name": membership.project.name},
                "count": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "next_page": page + 1 if page < total_pages else None,
                "results": rows,
            },
            status=status.HTTP_200_OK,
        )


class WorkItemDetailEndpoint(ExternalApiView):
    """GET → one work item with everything its screen shows."""

    def get(self, request, work_item_id):
        if not is_valid_uuid(str(work_item_id)):
            return error("Work item not found.", "WORK_ITEM_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        project_id = Issue.issue_objects.filter(pk=work_item_id).values_list("project_id", flat=True).first()
        membership = membership_for(request.user, project_id) if project_id else None
        issue = visible_work_items(membership).filter(pk=work_item_id).first() if membership else None
        if issue is None:
            return error("Work item not found.", "WORK_ITEM_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        return Response(work_item_detail(issue, S3Storage(request=request)), status=status.HTTP_200_OK)
