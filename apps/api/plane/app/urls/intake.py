# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path


from plane.app.views import (
    IntakeViewSet,
    IntakeIssueViewSet,
    IntakeWorkItemDescriptionVersionEndpoint,
    IntakeFormEndpoint,
    IntakeFormInviteEndpoint,
    IntakeFormResetLinkEndpoint,
)


urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-form/",
        IntakeFormEndpoint.as_view(),
        name="intake-form",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-form/reset-link/",
        IntakeFormResetLinkEndpoint.as_view(),
        name="intake-form-reset-link",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-form/invites/",
        IntakeFormInviteEndpoint.as_view(),
        name="intake-form-invites",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-form/invites/<uuid:pk>/",
        IntakeFormInviteEndpoint.as_view(),
        name="intake-form-invites",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intakes/",
        IntakeViewSet.as_view({"get": "list", "post": "create"}),
        name="intake",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intakes/<uuid:pk>/",
        IntakeViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="intake",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-issues/",
        IntakeIssueViewSet.as_view({"get": "list", "post": "create"}),
        name="intake-issue",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-issues/<uuid:pk>/",
        IntakeIssueViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="intake-issue",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/inboxes/",
        IntakeViewSet.as_view({"get": "list", "post": "create"}),
        name="inbox",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/inboxes/<uuid:pk>/",
        IntakeViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="inbox",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/inbox-issues/",
        IntakeIssueViewSet.as_view({"get": "list", "post": "create"}),
        name="inbox-issue",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/inbox-issues/<uuid:pk>/",
        IntakeIssueViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="inbox-issue",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-work-items/<uuid:work_item_id>/description-versions/",
        IntakeWorkItemDescriptionVersionEndpoint.as_view(),
        name="intake-work-item-versions",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/intake-work-items/<uuid:work_item_id>/description-versions/<uuid:pk>/",
        IntakeWorkItemDescriptionVersionEndpoint.as_view(),
        name="intake-work-item-versions",
    ),
]
