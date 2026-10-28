# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for ``?disposition=inline`` on the work item attachment endpoint,
used by the in-app attachment viewer."""

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import FileAsset, Issue, Project, ProjectMember

S3_STORAGE_PATH = "plane.app.views.issue.attachment.S3Storage"


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Test Project", identifier="TP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(db, workspace, project, create_user):
    return Issue.objects.create(name="Work item", workspace=workspace, project=project, created_by=create_user)


def make_attachment(workspace, project, issue, user, name, mime_type):
    return FileAsset.objects.create(
        attributes={"name": name, "type": mime_type, "size": 1024},
        asset=f"{workspace.id}/{name}",
        size=1024,
        workspace=workspace,
        project=project,
        issue=issue,
        created_by=user,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        is_uploaded=True,
    )


def attachment_url(workspace, project, issue, attachment):
    return (
        f"/api/assets/v2/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/attachments/{attachment.id}/"
    )


@pytest.mark.contract
class TestIssueAttachmentInlinePreview:
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "query, name, mime_type, expected_disposition, expected_content_type",
        [
            ("?disposition=inline", "report.pdf", "application/pdf", "inline", "application/pdf"),
            ("?disposition=inline", "data.csv", "text/csv", "inline", "text/plain; charset=utf-8"),
            # Script-capable files never go inline
            ("?disposition=inline", "page.html", "text/html", "attachment", None),
            ("?disposition=inline", "logo.svg", "image/svg+xml", "attachment", None),
            # Without the parameter the endpoint keeps downloading
            ("", "report.pdf", "application/pdf", "attachment", None),
        ],
    )
    def test_disposition(
        self,
        session_client,
        workspace,
        project,
        issue,
        create_user,
        query,
        name,
        mime_type,
        expected_disposition,
        expected_content_type,
    ):
        attachment = make_attachment(workspace, project, issue, create_user, name, mime_type)

        with mock.patch(S3_STORAGE_PATH) as mock_storage:
            mock_storage.return_value.generate_presigned_url.return_value = "https://signed.example/file"
            response = session_client.get(attachment_url(workspace, project, issue, attachment) + query)

        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"] == "https://signed.example/file"
        kwargs = mock_storage.return_value.generate_presigned_url.call_args.kwargs
        assert kwargs["disposition"] == expected_disposition
        assert kwargs["content_type"] == expected_content_type
        assert kwargs["filename"] == name
