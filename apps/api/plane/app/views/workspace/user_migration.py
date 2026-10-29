# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.http import HttpResponse

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Workspace
from plane.utils.user_migration_sheet import build_user_migration_sheet


class UserMigrationSheetEndpoint(BaseAPIView):
    """Download the user migration sheet (Excel) of the workspace: every member, their projects and project managers,
    and the compulsory Migrate? / Migrate To / Delete? columns the managers fill in to clean up Jira."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        content, content_type, file_name = build_user_migration_sheet(workspace)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{file_name}"'
        # the web app (another origin in development) reads the file name from it
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response
