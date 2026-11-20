# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .workspace_project_join import join_default_workspace, process_workspace_project_invitations


def post_user_auth_workflow(user, is_signup, request):
    process_workspace_project_invitations(user=user)
    # no invite: into the organization's workspace instead of a workspace of their own
    join_default_workspace(user)
