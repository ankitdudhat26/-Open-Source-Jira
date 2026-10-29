# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.http import HttpResponse

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ProjectMember
from plane.utils.work_item_export import EXPORT_FORMATS, export_work_items


class WorkItemExportEndpoint(BaseAPIView):
    """Download every work item (story) of a project as Word, Excel or CSV — like Jira's Export menu."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        export_format = request.query_params.get("file_type", "word")
        if export_format not in EXPORT_FORMATS:
            return Response(
                {"error": f"file_type must be one of {', '.join(EXPORT_FORMATS)}"}, status=status.HTTP_400_BAD_REQUEST
            )
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        # a client of a project that hides the work items of others exports only their own (as in the list)
        own_only = (
            not project.guest_view_all_features
            and ProjectMember.objects.filter(
                project_id=project_id, member=request.user, role=ROLE.GUEST.value, is_active=True
            ).exists()
        )
        content, content_type, file_name = export_work_items(
            project, export_format, user_id=request.user.id if own_only else None
        )
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{file_name}"'
        # the web app (another origin in development) reads the file name from it
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response
