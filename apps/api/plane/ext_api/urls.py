# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from .views import (
    LoginEndpoint,
    LogoutEndpoint,
    MeEndpoint,
    ProjectListEndpoint,
    ProjectWorkItemListEndpoint,
    WorkItemDetailEndpoint,
)

urlpatterns = [
    path("auth/login/", LoginEndpoint.as_view(), name="ext-api-login"),
    path("auth/logout/", LogoutEndpoint.as_view(), name="ext-api-logout"),
    path("me/", MeEndpoint.as_view(), name="ext-api-me"),
    path("projects/", ProjectListEndpoint.as_view(), name="ext-api-projects"),
    path(
        "projects/<uuid:project_id>/work-items/",
        ProjectWorkItemListEndpoint.as_view(),
        name="ext-api-project-work-items",
    ),
    path("work-items/<uuid:work_item_id>/", WorkItemDetailEndpoint.as_view(), name="ext-api-work-item"),
]
