# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A project's work items open as a spreadsheet the first time; the layout a person picks is kept for them."""

import pytest
from rest_framework import status


@pytest.mark.contract
class TestDefaultWorkItemLayout:
    @pytest.mark.django_db
    def test_spreadsheet_first_then_the_persons_choice(self, session_client, workspace):
        created = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/", {"name": "Layout", "identifier": "LAYT"}, format="json"
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        url = f"/api/workspaces/{workspace.slug}/projects/{created.data['id']}/user-properties/"

        first = session_client.get(url).data
        filters = {**first["display_filters"], "layout": "kanban"}
        session_client.patch(url, {"display_filters": filters}, format="json")
        again = session_client.get(url).data

        assert first["display_filters"]["layout"] == "spreadsheet"
        assert again["display_filters"]["layout"] == "kanban"
