# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The Work items assignee filter (also behind the resource avatars above the list, as in Jira): one or more people,
"none" for work items nobody is assigned to, or both."""

import json
from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Issue, IssueAssignee, Project, ProjectMember, State, User, WorkspaceMember


@pytest.fixture
def setup(db, workspace, create_user):
    project = Project.objects.create(name="Printing", identifier="PRN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    state = State.objects.create(name="To Do", group="unstarted", project=project, workspace=workspace, default=True)
    people = {}
    for name in ("divyesh", "raju"):
        user = User.objects.create(email=f"{name}-{uuid4().hex[:6]}@example.com", username=f"{name}_{uuid4().hex[:6]}")
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=15)
        people[name] = user
    for title, assignees in [
        ("Mail testing", ["divyesh"]),
        ("New request", ["raju"]),
        ("Pairing", ["divyesh", "raju"]),
        ("Sales", []),
        ("Test", []),
    ]:
        issue = Issue.objects.create(name=title, project=project, workspace=workspace, state=state)
        for name in assignees:
            IssueAssignee.objects.create(issue=issue, assignee=people[name], project=project, workspace=workspace)
    # a removed assignment does not count: the item is unassigned again
    removed = Issue.objects.create(name="Reassigned away", project=project, workspace=workspace, state=state)
    IssueAssignee.objects.create(issue=removed, assignee=people["raju"], project=project, workspace=workspace).delete()
    return project, people


def _names(session_client, workspace, project, *values):
    response = session_client.get(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/",
        {"per_page": 100, "cursor": "100:0:0", "filters": json.dumps({"and": [{"assignee_id__in": ",".join(values)}]})},
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return sorted(issue["name"] for issue in response.data["results"])


@pytest.mark.contract
class TestAssigneeFilter:
    @pytest.mark.django_db
    def test_one_or_more_people(self, session_client, workspace, setup):
        project, people = setup

        assert _names(session_client, workspace, project, str(people["divyesh"].id)) == ["Mail testing", "Pairing"]
        assert _names(session_client, workspace, project, str(people["divyesh"].id), str(people["raju"].id)) == [
            "Mail testing",
            "New request",
            "Pairing",
        ]

    @pytest.mark.django_db
    def test_unassigned_alone_and_with_people(self, session_client, workspace, setup):
        project, people = setup

        assert _names(session_client, workspace, project, "none") == ["Reassigned away", "Sales", "Test"]
        assert _names(session_client, workspace, project, "none", str(people["raju"].id)) == [
            "New request",
            "Pairing",
            "Reassigned away",
            "Sales",
            "Test",
        ]
