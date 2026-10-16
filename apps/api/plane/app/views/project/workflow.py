# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Project
from plane.utils.workflow import WorkflowError, apply_template, save_workflow, serialize_workflow


class ProjectWorkflowEndpoint(BaseAPIView):
    """Read the project's workflow (every member, to know the allowed moves) and replace it (admins)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        return Response(serialize_workflow(project_id), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def put(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        try:
            data = save_workflow(
                project,
                request.data.get("is_enabled", False),
                request.data.get("transitions", []),
                request.user.id,
            )
        except WorkflowError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data, status=status.HTTP_200_OK)


class ProjectWorkflowTemplateEndpoint(BaseAPIView):
    """Apply a ready made workflow (adds its missing states and transitions, turns the workflow on)."""

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        try:
            data = apply_template(project, request.data.get("template"), request.user.id)
        except WorkflowError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data, status=status.HTTP_200_OK)
