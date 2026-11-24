# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json
import mimetypes
import re

# Django imports
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.app.serializers import IssueAttachmentSerializer, IssueCommentSerializer, IssueCreateSerializer
from plane.bgtasks.intake_request_status_task import intake_request_received
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import FileAsset, IntakeForm, IntakeIssue, Issue, Project, State, StateGroup
from plane.db.models.intake import SourceType
from plane.settings.storage import S3Storage
from plane.utils.asset_paths import asset_storage_key
from plane.utils.host import base_host
from plane.utils.intake_form import (
    invited_projects,
    is_invited,
    open_form_filter,
    project_form,
    resolve_role_labels,
    strip_hidden_fields,
    user_requests,
    visible_fields,
)
from plane.utils.intake_portal import (
    allowed_states,
    set_full_name,
    notifications,
    visible_work_items,
    work_item_detail,
    work_item_row,
)
from plane.utils.path_validator import sanitize_filename
from plane.utils.work_item_automation import run_work_item_automation
from plane.utils.workflow import check_transition

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
                # the name the team sees on their requests
                "full_name": f"{request.user.first_name or ''} {request.user.last_name or ''}".strip(),
                # only a client with no name (an account made before the sign-up form asked for it) is asked for it
                "needs_name": not (request.user.first_name or "").strip()
                and not (request.user.last_name or "").strip(),
                "forms": [project_form(project) for project in _client_projects(request.user, form)],
            },
            status=status.HTTP_200_OK,
        )


class IntakeFormProfileEndpoint(BaseAPIView):
    """The invited client's full name, which the team sees on their requests (asked once when it is missing)."""

    def patch(self, request, anchor):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        if not set_full_name(request.user, request.data.get("full_name")):
            return Response({"error": "Enter your full name."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"full_name": f"{request.user.first_name} {request.user.last_name}".strip(), "needs_name": False},
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
            # the project's roles only (a role without a label gets one)
            issue_data["label_ids"] = resolve_role_labels(project, issue_data["label_ids"])

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
        # the members switched on in Settings → Intake get an email (once the request is saved)
        app_url = base_host(request=request, is_app=True)
        transaction.on_commit(lambda: intake_request_received.delay(str(intake_issue.id), app_url))
        return Response(
            {"id": str(intake_issue.id), "issue_id": str(issue.id), "project_id": str(project.id)},
            status=status.HTTP_201_CREATED,
        )


def _store_attachment(request, issue):
    """Store the uploaded file as an attachment of the work item (as in the app), or return an error Response."""
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
        return _store_attachment(request, issue)


def _client_work_item(request, anchor, issue_id):
    """(form, work item) the client may see through the link, or (None, None)."""
    form = _form(anchor)
    if not form or not is_invited(request.user, form.project_id):
        return None, None
    issue = visible_work_items(request.user, _client_projects(request.user, form)).filter(pk=issue_id).first()
    return form, issue


class IntakeFormWorkItemListEndpoint(BaseAPIView):
    """The project's work items the client may see (as in the app), for the Work Items tab."""

    def get(self, request, anchor):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        issues = visible_work_items(request.user, _client_projects(request.user, form))
        return Response([work_item_row(issue, request.user) for issue in issues], status=status.HTTP_200_OK)


class IntakeFormWorkItemEndpoint(BaseAPIView):
    """A work item's details for the client (description, files, comments, history) and moving it to another state —
    the only change a client makes; the project's workflow decides which states they may move it to."""

    def get(self, request, anchor, issue_id):
        _, issue = _client_work_item(request, anchor, issue_id)
        if not issue:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(work_item_detail(issue, request.user, S3Storage(request=request)), status=status.HTTP_200_OK)

    def patch(self, request, anchor, issue_id):
        _, issue = _client_work_item(request, anchor, issue_id)
        if not issue:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        if set(request.data.keys()) - {"state_id"}:
            return Response({"error": "Only the state can be changed."}, status=status.HTTP_400_BAD_REQUEST)
        state_id = str(request.data.get("state_id") or "")
        if state_id not in {state["id"] for state in allowed_states(issue, request.user)}:
            error = check_transition(issue.project_id, issue.state_id, state_id, request.user.id)
            return Response(
                {"error": error or "This work item cannot be moved to that state."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        current_instance = json.dumps({"state_id": str(issue.state_id)}, cls=DjangoJSONEncoder)
        issue.state_id = state_id
        issue.save(update_fields=["state", "updated_at"])
        origin = base_host(request=request, is_app=True)
        # the parent feature follows its tasks' status, as when the team moves it
        run_work_item_automation(issue.id, request.user.id, origin=origin, state_changed=True)
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"state_id": state_id}, cls=DjangoJSONEncoder),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=current_instance,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=origin,
        )
        issue.refresh_from_db()
        return Response(work_item_detail(issue, request.user, S3Storage(request=request)), status=status.HTTP_200_OK)


class IntakeFormWorkItemCommentEndpoint(BaseAPIView):
    """A comment of the client on a work item they may see; the team sees it with the work item's comments."""

    def post(self, request, anchor, issue_id):
        _, issue = _client_work_item(request, anchor, issue_id)
        if not issue:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        comment_html = str(request.data.get("comment_html") or "").strip()
        if not comment_html:
            return Response({"error": "Write a comment."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = IssueCommentSerializer(data={"comment_html": comment_html})
        if not serializer.is_valid():
            return Response({"error": "Check the comment and try again."}, status=status.HTTP_400_BAD_REQUEST)
        comment = serializer.save(project_id=issue.project_id, issue_id=issue.id, actor=request.user)
        # the images the client put in the comment now belong to it
        image_ids = set(COMMENT_IMAGE_SRC.findall(comment_html))
        if image_ids:
            FileAsset.objects.filter(
                id__in=image_ids,
                created_by=request.user,
                project_id=issue.project_id,
                entity_type=FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
                comment__isnull=True,
            ).update(comment_id=comment.id)
        issue_activity.delay(
            type="comment.activity.created",
            requested_data=json.dumps(serializer.data, cls=DjangoJSONEncoder),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=base_host(request=request, is_app=True),
        )
        return Response({"id": serializer.data["id"]}, status=status.HTTP_201_CREATED)


class IntakeFormWorkItemAttachmentEndpoint(BaseAPIView):
    """A file the client attaches to a work item they may see (with a comment, or on its own)."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, anchor, issue_id):
        _, issue = _client_work_item(request, anchor, issue_id)
        if not issue:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        return _store_attachment(request, issue)


COMMENT_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
# an image of a comment, as the editor writes it: <image-component src="<asset id>" …>
COMMENT_IMAGE_SRC = re.compile(
    r"<image-component\b[^>]*\bsrc=[\"']([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})[\"']"
)


class IntakeFormWorkItemCommentImageEndpoint(BaseAPIView):
    """An image the client puts in a comment (as in the app: it shows in the comment, for the team too)."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, anchor, issue_id):
        _, issue = _client_work_item(request, anchor, issue_id)
        if not issue:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "Choose an image."}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > settings.FILE_SIZE_LIMIT:
            return Response(
                {"error": f"Images can be up to {settings.FILE_SIZE_LIMIT // (1024 * 1024)} MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = sanitize_filename(upload.name) or "image"
        content_type = (upload.content_type or "").split(";")[0].strip().lower()
        if content_type not in COMMENT_IMAGE_TYPES:
            return Response(
                {"error": "Only JPEG, PNG, WebP and GIF images can be put in a comment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        asset_key = asset_storage_key(
            name, entity_type=FileAsset.EntityTypeContext.COMMENT_DESCRIPTION, workspace_id=issue.workspace_id
        )
        if not S3Storage(request=request).upload_file(upload, asset_key, content_type):
            return Response({"error": "The image could not be stored. Try again."}, status=500)
        asset = FileAsset.objects.create(
            attributes={"name": name, "type": content_type, "size": upload.size},
            asset=asset_key,
            size=upload.size,
            workspace_id=issue.workspace_id,
            project_id=issue.project_id,
            entity_type=FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
            is_uploaded=True,
        )
        return Response({"asset_id": str(asset.id)}, status=status.HTTP_201_CREATED)


class IntakeFormAssetEndpoint(BaseAPIView):
    """An image in a description or comment of a work item the client may see: opens the stored file."""

    def get(self, request, anchor, asset_id):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        asset = FileAsset.objects.filter(
            pk=asset_id,
            project__in=_client_projects(request.user, form),
            is_uploaded=True,
            entity_type__in=[
                FileAsset.EntityTypeContext.COMMENT_DESCRIPTION,
                FileAsset.EntityTypeContext.ISSUE_DESCRIPTION,
            ],
        ).first()
        if not asset:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        download = request.query_params.get("download") == "1"
        url = S3Storage(request=request).generate_presigned_url(
            object_name=asset.asset.name,
            disposition="attachment" if download else "inline",
            filename=asset.attributes.get("name"),
        )
        return HttpResponseRedirect(url)


class IntakeFormNotificationEndpoint(BaseAPIView):
    """What happened to the client's requests and work items, for the bell in the header."""

    def get(self, request, anchor):
        form = _form(anchor)
        if not form or not is_invited(request.user, form.project_id):
            return Response(NOT_AVAILABLE, status=status.HTTP_404_NOT_FOUND)
        return Response(notifications(request.user, _client_projects(request.user, form)), status=status.HTTP_200_OK)
