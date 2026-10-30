# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
import mimetypes

# Django imports
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.app.serializers import IssueAttachmentSerializer, IssueCreateSerializer
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import FileAsset, IntakeForm, IntakeIssue, Issue, Label, Project, State, StateGroup
from plane.db.models.intake import SourceType
from plane.settings.storage import S3Storage
from plane.utils.asset_paths import asset_storage_key
from plane.utils.host import base_host
from plane.utils.intake_form import (
    invited_projects,
    is_invited,
    open_form_filter,
    project_form,
    strip_hidden_fields,
    user_requests,
    visible_fields,
)
from plane.utils.path_validator import sanitize_filename

NOT_AVAILABLE = {"error": "This form is not available. Ask the person who shared it for a new link."}


def _form(anchor):
    """The form behind a link, while it takes requests."""
    return (
        IntakeForm.objects.filter(anchor=anchor, project__in=Project.objects.filter(open_form_filter()))
        .select_related("project", "project__workspace")
        .first()
    )


def _client_projects(user, form):
    """The projects of the link's workspace whose form the user was invited to — the link's own project first."""
    projects = [project for project in invited_projects(user) if project.workspace_id == form.project.workspace_id]
    return sorted(projects, key=lambda project: project.id != form.project_id)


def _client_project(user, form, project_id):
    return next((project for project in _client_projects(user, form) if str(project.id) == str(project_id)), None)


class IntakeFormPortalEndpoint(BaseAPIView):
    """What the link shows: a login prompt, "not invited", or — for an invited client — the forms of their projects."""

    permission_classes = [AllowAny]

    def get(self, request, anchor):
        form = _form(anchor)
        if not form:
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        data = {"project_name": form.project.name, "workspace_name": form.project.workspace.name}
        if not request.user.is_authenticated:
            return Response({**data, "access": "login"}, status=status.HTTP_200_OK)
        if not is_invited(request.user, form.project_id):
            return Response({**data, "access": "not_invited", "email": request.user.email}, status=status.HTTP_200_OK)
        return Response(
            {
                **data,
                "access": "ok",
                "email": request.user.email,
                "forms": [project_form(project) for project in _client_projects(request.user, form)],
            },
            status=status.HTTP_200_OK,
        )


class IntakeFormRequestEndpoint(BaseAPIView):
    """The requests an invited client sent (with their status and the decline reason) and sending a new one."""

    def get(self, request, anchor):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        project_ids = [project.id for project in _client_projects(request.user, form)]
        return Response(user_requests(request.user, project_ids), status=status.HTTP_200_OK)

    def post(self, request, anchor):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        project = _client_project(request.user, form, request.data.get("project_id") or form.project_id)
        if not project:
            return Response({"error": "You cannot send requests to this project."}, status=status.HTTP_403_FORBIDDEN)

        issue_data = request.data.get("issue")
        if not isinstance(issue_data, dict) or not str(issue_data.get("name") or "").strip():
            return Response({"error": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)
        # only what the project's form shows; labels of this project only; the rest is for the project team
        issue_data = strip_hidden_fields(project.id, issue_data)
        allowed = {"name", "description_html", "type_id", "priority", "label_ids"}
        issue_data = {key: value for key, value in issue_data.items() if key in allowed}
        issue_data["name"] = str(issue_data["name"]).strip()[:255]
        if issue_data.get("label_ids"):
            issue_data["label_ids"] = [
                str(label_id)
                for label_id in Label.objects.filter(project=project, id__in=issue_data["label_ids"]).values_list(
                    "id", flat=True
                )
            ]

        triage_state = State.triage_objects.filter(project=project).first() or State.objects.create(
            name="Triage",
            group=StateGroup.TRIAGE.value,
            project=project,
            workspace_id=project.workspace_id,
            color="#4E5355",
            sequence=65000,
            default=False,
        )
        issue_data["state_id"] = str(triage_state.id)
        serializer = IssueCreateSerializer(
            data=issue_data,
            context={
                "project_id": project.id,
                "workspace_id": project.workspace_id,
                "default_assignee_id": project.default_assignee_id,
                "allow_triage_state": True,
            },
        )
        if not serializer.is_valid():
            return Response({"error": "Check the request and try again.", "fields": serializer.errors}, status=400)
        issue = serializer.save()
        intake = project.project_intake.filter(is_default=True).first() or project.project_intake.first()
        if not intake:
            intake = project.project_intake.create(name=f"{project.name} Intake", is_default=True)
        intake_issue = IntakeIssue.objects.create(
            intake=intake, project=project, issue=issue, source=SourceType.IN_APP, source_email=request.user.email
        )
        issue_activity.delay(
            type="issue.activity.created",
            requested_data=json.dumps(issue_data, cls=DjangoJSONEncoder),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(project.id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=base_host(request=request, is_app=True),
            intake=str(intake_issue.id),
        )
        return Response(
            {"id": str(intake_issue.id), "issue_id": str(issue.id), "project_id": str(project.id)},
            status=status.HTTP_201_CREATED,
        )


class IntakeFormAttachmentEndpoint(BaseAPIView):
    """A file on a request the client sent, while the project's form takes attachments. The file comes through the
    API (the client is not a member of the project) and is stored like any work item attachment."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, anchor, issue_id):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        issue = Issue.objects.filter(pk=issue_id, created_by=request.user, issue_intake__isnull=False).first()
        if not issue or not _client_project(request.user, form, issue.project_id):
            return Response({"error": "Request not found."}, status=status.HTTP_404_NOT_FOUND)
        if "attachments" not in visible_fields(issue.project_id):
            return Response(
                {"error": "This project's request form does not take attachments."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "Choose a file."}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > settings.FILE_SIZE_LIMIT:
            return Response(
                {"error": f"Files can be up to {settings.FILE_SIZE_LIMIT // (1024 * 1024)} MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = sanitize_filename(upload.name) or "unnamed"
        content_type = (upload.content_type or "").split(";")[0].strip().lower()
        if content_type not in settings.ATTACHMENT_MIME_TYPES:
            content_type = (mimetypes.guess_type(name)[0] or "").lower()
        if content_type not in settings.ATTACHMENT_MIME_TYPES:
            return Response({"error": "This type of file cannot be attached."}, status=status.HTTP_400_BAD_REQUEST)

        asset_key = asset_storage_key(
            name, entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT, workspace_id=issue.workspace_id
        )
        if not S3Storage(request=request).upload_file(upload, asset_key, content_type):
            return Response({"error": "The file could not be stored. Try again."}, status=500)
        asset = FileAsset.objects.create(
            attributes={"name": name, "type": content_type, "size": upload.size},
            asset=asset_key,
            size=upload.size,
            workspace_id=issue.workspace_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            is_uploaded=True,
        )
        issue_activity.delay(
            type="attachment.activity.created",
            requested_data=None,
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=json.dumps(IssueAttachmentSerializer(asset).data, cls=DjangoJSONEncoder),
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=base_host(request=request, is_app=True),
        )
        return Response({"id": str(asset.id), "name": name}, status=status.HTTP_201_CREATED)
