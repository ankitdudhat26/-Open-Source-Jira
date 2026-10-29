# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.exceptions import ValidationError
from django.http import HttpResponse

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ProjectMember
from plane.utils.host import base_host
from plane.utils.work_item_export import EXPORT_FORMATS, FILTER_NAMES, export_filter_options, export_work_items


def _own_only(request, project):
    """A client of a project that hides the work items of others exports only their own (as in the list)."""
    return (
        not project.guest_view_all_features
        and ProjectMember.objects.filter(
            project_id=project.id, member=request.user, role=ROLE.GUEST.value, is_active=True
        ).exists()
    )


def _filters(request):
    """The filters of the export from the query: ?state=<id>,<id>&assignee=<id>… (see FILTER_NAMES)."""
    filters = {}
    for name in FILTER_NAMES:
        values = [value.strip() for value in request.query_params.get(name, "").split(",") if value.strip()]
        if values:
            filters[name] = values
    return filters


class WorkItemExportOptionsEndpoint(BaseAPIView):
    """What the export of the work items of a project can be filtered by."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        user_id = request.user.id if _own_only(request, project) else None
        return Response(export_filter_options(project, user_id=user_id), status=status.HTTP_200_OK)


class WorkItemExportEndpoint(BaseAPIView):
    """Download the work items (stories) of a project as Word, Excel or CSV — all of them or the ones matching the
    filters — like Jira's Export menu."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        export_format = request.query_params.get("file_type", "word")
        if export_format not in EXPORT_FORMATS:
            return Response(
                {"error": f"file_type must be one of {', '.join(EXPORT_FORMATS)}"}, status=status.HTTP_400_BAD_REQUEST
            )
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        try:
            content, content_type, file_name = export_work_items(
                project,
                export_format,
                user_id=request.user.id if _own_only(request, project) else None,
                filters=_filters(request),
                app_url=base_host(request=request, is_app=True),
            )
        except ValidationError:
            return Response({"error": "A filter has an invalid value"}, status=status.HTTP_400_BAD_REQUEST)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{file_name}"'
        # the web app (another origin in development) reads the file name from it
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response
