# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path


from plane.space.views import (
    IntakeIssuePublicViewSet,
    WorkspaceProjectDeployBoardEndpoint,
    IntakeFormAttachmentEndpoint,
    IntakeFormPortalEndpoint,
    IntakeFormRequestEndpoint,
    IntakeFormWorkItemListEndpoint,
    IntakeFormWorkItemEndpoint,
    IntakeFormWorkItemCommentEndpoint,
    IntakeFormWorkItemAttachmentEndpoint,
    IntakeFormNotificationEndpoint,
    IntakeFormWorkItemCommentImageEndpoint,
    IntakeFormAssetEndpoint,
)


urlpatterns = [
    path(
        "intake-forms/<str:anchor>/",
        IntakeFormPortalEndpoint.as_view(),
        name="intake-form-portal",
    ),
    path(
        "intake-forms/<str:anchor>/requests/",
        IntakeFormRequestEndpoint.as_view(),
        name="intake-form-requests",
    ),
    path(
        "intake-forms/<str:anchor>/requests/<uuid:issue_id>/attachments/",
        IntakeFormAttachmentEndpoint.as_view(),
        name="intake-form-request-attachments",
    ),
    # the client's Work Items tab, a work item's details (comment, attach, move to another state) and notifications
    path(
        "intake-forms/<str:anchor>/work-items/",
        IntakeFormWorkItemListEndpoint.as_view(),
        name="intake-form-work-items",
    ),
    path(
        "intake-forms/<str:anchor>/work-items/<uuid:issue_id>/",
        IntakeFormWorkItemEndpoint.as_view(),
        name="intake-form-work-item",
    ),
    path(
        "intake-forms/<str:anchor>/work-items/<uuid:issue_id>/comments/",
        IntakeFormWorkItemCommentEndpoint.as_view(),
        name="intake-form-work-item-comments",
    ),
    path(
        "intake-forms/<str:anchor>/work-items/<uuid:issue_id>/attachments/",
        IntakeFormWorkItemAttachmentEndpoint.as_view(),
        name="intake-form-work-item-attachments",
    ),
    path(
        "intake-forms/<str:anchor>/work-items/<uuid:issue_id>/comment-images/",
        IntakeFormWorkItemCommentImageEndpoint.as_view(),
        name="intake-form-work-item-comment-images",
    ),
    path(
        "intake-forms/<str:anchor>/assets/<uuid:asset_id>/",
        IntakeFormAssetEndpoint.as_view(),
        name="intake-form-asset",
    ),
    path(
        "intake-forms/<str:anchor>/notifications/",
        IntakeFormNotificationEndpoint.as_view(),
        name="intake-form-notifications",
    ),
    path(
        "anchor/<str:anchor>/intakes/<uuid:intake_id>/intake-issues/",
        IntakeIssuePublicViewSet.as_view({"get": "list", "post": "create"}),
        name="intake-issue",
    ),
    path(
        "anchor/<str:anchor>/intakes/<uuid:intake_id>/inbox-issues/",
        IntakeIssuePublicViewSet.as_view({"get": "list", "post": "create"}),
        name="inbox-issue",
    ),
    path(
        "anchor/<str:anchor>/intakes/<uuid:intake_id>/intake-issues/<uuid:pk>/",
        IntakeIssuePublicViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="intake-issue",
    ),
    path(
        "workspaces/<str:slug>/project-boards/",
        WorkspaceProjectDeployBoardEndpoint.as_view(),
        name="workspace-project-boards",
    ),
]
