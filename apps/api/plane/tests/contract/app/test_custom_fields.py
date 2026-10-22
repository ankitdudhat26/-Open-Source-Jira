# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

import pytest
from rest_framework import status

from plane.db.models import (
    CustomField,
    CustomFieldValue,
    Issue,
    IssueActivity,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Fields", "identifier": "FLD"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def url(workspace, project, path):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/{path}"


def member(workspace, project, role):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(email=f"u-{suffix}@example.com", username=f"u_{suffix}", display_name=f"u{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=role, designation="Dev")
    return user


def create_field(session_client, workspace, project, **data):
    response = session_client.post(url(workspace, project, "custom-fields/"), data, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return CustomField.objects.get(pk=response.data["id"])


@pytest.mark.contract
class TestCustomFields:
    @pytest.mark.django_db
    def test_admin_creates_fields_of_each_type(self, session_client, workspace, project):
        create_field(session_client, workspace, project, name="Story points", field_type="number")
        create_field(
            session_client, workspace, project, name="Task Type", field_type="select", options=["UI", "API", "UI"]
        )

        listed = session_client.get(url(workspace, project, "custom-fields/")).data
        assert [(field["name"], field["field_type"]) for field in listed] == [
            ("Story points", "number"),
            ("Task Type", "select"),
        ]
        assert listed[1]["options"] == ["UI", "API"]
        # duplicate names and empty dropdowns are refused
        response = session_client.post(
            url(workspace, project, "custom-fields/"), {"name": "Story points"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response = session_client.post(
            url(workspace, project, "custom-fields/"), {"name": "Area", "field_type": "select"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_values_are_validated_and_recorded_in_history(self, session_client, workspace, project, create_user):
        points = create_field(session_client, workspace, project, name="Story points", field_type="number")
        kind = create_field(
            session_client, workspace, project, name="Task Type", field_type="select", options=["UI", "API"]
        )
        people = create_field(session_client, workspace, project, name="Reviewers", field_type="user")
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace)
        values_url = url(workspace, project, f"issues/{issue.id}/custom-field-values/")

        assert (
            session_client.put(values_url, {"field_id": str(points.id), "value": "8"}, format="json").data["value"] == 8
        )
        assert (
            session_client.put(values_url, {"field_id": str(kind.id), "value": "API"}, format="json").status_code == 200
        )
        assert (
            session_client.put(values_url, {"field_id": str(kind.id), "value": "Other"}, format="json").status_code
            == 400
        )
        assert (
            session_client.put(values_url, {"field_id": str(points.id), "value": "lots"}, format="json").status_code
            == 400
        )
        assert (
            session_client.put(
                values_url, {"field_id": str(people.id), "value": [str(create_user.id)]}, format="json"
            ).status_code
            == 200
        )
        outsider = User.objects.create(email="out@example.com", username="out")
        assert (
            session_client.put(
                values_url, {"field_id": str(people.id), "value": [str(outsider.id)]}, format="json"
            ).status_code
            == 400
        )

        assert session_client.get(values_url).data == {
            str(points.id): 8,
            str(kind.id): "API",
            str(people.id): [str(create_user.id)],
        }
        entry = IssueActivity.objects.get(issue=issue, field="custom_field", external_field_name="Task Type")
        assert (entry.old_value, entry.new_value, entry.actor_id) == ("", "API", create_user.id)

        # clearing a value removes it and is recorded too
        session_client.put(values_url, {"field_id": str(points.id), "value": None}, format="json")
        assert not CustomFieldValue.objects.filter(issue=issue, field=points).exists()
        assert IssueActivity.objects.filter(issue=issue, external_field_name="Story points").count() == 2

    @pytest.mark.django_db
    def test_permissions(self, api_client, session_client, workspace, project):
        field = create_field(session_client, workspace, project, name="Area", field_type="text")
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace)
        developer, client = member(workspace, project, 15), member(workspace, project, 5)
        values_url = url(workspace, project, f"issues/{issue.id}/custom-field-values/")

        api_client.force_authenticate(user=developer)
        assert (
            api_client.post(url(workspace, project, "custom-fields/"), {"name": "X"}, format="json").status_code == 403
        )
        assert api_client.put(values_url, {"field_id": str(field.id), "value": "UI"}, format="json").status_code == 200

        api_client.force_authenticate(user=client)
        assert api_client.get(url(workspace, project, "custom-fields/")).status_code == 200
        assert api_client.get(values_url).status_code == 200
        assert api_client.put(values_url, {"field_id": str(field.id), "value": "API"}, format="json").status_code == 403

    @pytest.mark.django_db
    def test_type_is_locked_once_used_and_delete_removes_values(self, session_client, workspace, project):
        field = create_field(session_client, workspace, project, name="Area", field_type="text")
        issue = Issue.objects.create(name="Login", project=project, workspace=workspace)
        session_client.put(
            url(workspace, project, f"issues/{issue.id}/custom-field-values/"),
            {"field_id": str(field.id), "value": "UI"},
            format="json",
        )
        detail = url(workspace, project, f"custom-fields/{field.id}/")

        assert session_client.patch(detail, {"field_type": "number"}, format="json").status_code == 400
        assert session_client.patch(detail, {"name": "Area of work"}, format="json").data["name"] == "Area of work"
        assert session_client.delete(detail).status_code == 204
        assert not CustomFieldValue.objects.filter(issue=issue).exists()
