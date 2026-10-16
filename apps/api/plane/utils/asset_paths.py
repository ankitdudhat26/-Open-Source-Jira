# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Object storage paths of uploaded files.

Everything Plane uploads lives under one folder of the bucket (AWS_S3_FOLDER, default "plane"), so the bucket can be
shared with other applications, and is organised by owner and by kind of file:

    plane/workspaces/<workspace id>/attachments/<uuid>-<file name>
    plane/workspaces/<workspace id>/descriptions/...
    plane/users/<user id>/avatars/...
"""

# Python imports
import uuid

# Django imports
from django.conf import settings

# Sub folder per kind of file (FileAsset.EntityTypeContext)
ENTITY_FOLDERS = {
    "ISSUE_ATTACHMENT": "attachments",
    "ISSUE_DESCRIPTION": "descriptions",
    "COMMENT_DESCRIPTION": "comments",
    "PAGE_DESCRIPTION": "pages",
    "USER_AVATAR": "avatars",
    "USER_COVER": "covers",
    "WORKSPACE_LOGO": "logos",
    "PROJECT_COVER": "project-covers",
    "DRAFT_ISSUE_ATTACHMENT": "drafts/attachments",
    "DRAFT_ISSUE_DESCRIPTION": "drafts/descriptions",
}
DEFAULT_FOLDER = "files"


def asset_storage_key(name, entity_type=None, workspace_id=None, user_id=None):
    """Storage key for a new upload.

    Files of a workspace go under workspaces/<id>/, files of a user (avatar, cover) under users/<id>/.
    """
    if workspace_id:
        owner = f"workspaces/{workspace_id}"
    elif user_id:
        owner = f"users/{user_id}"
    else:
        owner = "shared"
    folder = ENTITY_FOLDERS.get(str(entity_type or ""), DEFAULT_FOLDER)
    parts = [getattr(settings, "AWS_S3_FOLDER", ""), owner, folder, f"{uuid.uuid4().hex}-{name}"]
    return "/".join(part.strip("/") for part in parts if part)
