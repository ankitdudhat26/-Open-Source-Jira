# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Groups (DevOps) and their queues: send to queue, counts, read only view, self assign, edit after taking."""

import uuid
from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    Project,
    ProjectMember,
    QueueItem,
    State,
    User,
    WorkspaceGroup,
    WorkspaceMember,
)

MEMBER, ADMIN = 15, 20


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.workspace.group.issue_activity.delay"),
        mock.patch("plane.bgtasks.issue_activities_task.issue_activity.delay"),
    ):
        yield


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Shop", "identifier": "SHOP"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def workspace_user(workspace, role=MEMBER):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(email=f"ops-{suffix}@example.com", username=f"ops_{suffix}", display_name=f"ops{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


def devops_group(session_client, workspace):
    response = session_client.get(f"/api/workspaces/{workspace.slug}/groups/")
    assert response.status_code == status.HTTP_200_OK
    group = next(group for group in response.data["groups"] if group["name"] == "DevOps")
    return WorkspaceGroup.objects.get(pk=group["id"])


def add_to_group(session_client, workspace, group, *users):
    response = session_client.patch(
        f"/api/workspaces/{workspace.slug}/groups/{group.id}/",
        {"member_ids": [str(user.id) for user in users]},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.data


def send(session_client, workspace, project, issue, group):
    return session_client.put(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/queue/",
        {"group_id": str(group.id) if group else None},
        format="json",
    )


def queue_url(workspace, group, path=""):
    return f"/api/workspaces/{workspace.slug}/queues/{group.id}/{path}"


@pytest.mark.contract
class TestGroups:
    @pytest.mark.django_db
    def test_devops_group_exists_with_a_queue_and_all_rights(self, session_client, workspace):
        response = session_client.get(f"/api/workspaces/{workspace.slug}/groups/")

        devops = next(group for group in response.data["groups"] if group["name"] == "DevOps")
        assert devops["has_queue"] is True
        assert set(devops["permissions"]) == {"queue.view", "queue.self_assign", "queue.edit_assigned"}
        assert {right["key"] for right in response.data["permissions"]} == set(devops["permissions"])
        # asking again does not create a second DevOps group
        session_client.get(f"/api/workspaces/{workspace.slug}/groups/")
        assert WorkspaceGroup.objects.filter(workspace=workspace, name="DevOps").count() == 1

    @pytest.mark.django_db
    def test_admin_creates_a_group_with_rights_and_members(self, session_client, workspace):
        qa = workspace_user(workspace)

        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/groups/",
            {"name": "QA", "permissions": ["queue.self_assign"], "member_ids": [str(qa.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        # seeing the queue comes with any queue right
        assert response.data["permissions"] == ["queue.view", "queue.self_assign"]
        assert response.data["member_ids"] == [str(qa.id)]

    @pytest.mark.django_db
    def test_only_admins_manage_groups(self, api_client, workspace):
        member = workspace_user(workspace)
        api_client.force_authenticate(user=member)

        response = api_client.post(f"/api/workspaces/{workspace.slug}/groups/", {"name": "Ops"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_unknown_rights_are_rejected(self, session_client, workspace):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/groups/", {"name": "Ops", "permissions": ["root"]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
class TestDevOpsQueue:
    @pytest.mark.django_db
    def test_full_flow(self, session_client, api_client, workspace, project):
        group = devops_group(session_client, workspace)
        engineer = workspace_user(workspace)  # not a member of the project
        add_to_group(session_client, workspace, group, engineer)
        issue = Issue.objects.create(name="Set up staging server", project=project, workspace=workspace)

        # a project member sends the work item to the DevOps queue
        response = send(session_client, workspace, project, issue, group)
        assert response.status_code == status.HTTP_200_OK, response.data
        assert QueueItem.objects.filter(issue=issue, group=group).exists()

        api_client.force_authenticate(user=engineer)
        # the queue is counted
        queues = api_client.get(f"/api/workspaces/{workspace.slug}/queues/").data
        devops = next(queue for queue in queues if queue["group"]["name"] == "DevOps")
        assert devops["counts"] == {"open": 1, "unassigned": 1, "mine": 0, "done": 0}

        # read only view with the project's name, even without project membership
        items = api_client.get(queue_url(workspace, group, "items/?filter=unassigned")).data
        assert [item["key"] for item in items] == [f"SHOP-{issue.sequence_id}"]
        assert items[0]["project"]["name"] == "Shop"
        detail = api_client.get(queue_url(workspace, group, f"items/{issue.id}/")).data
        assert detail["can_self_assign"] is True
        assert detail["can_edit"] is False
        done = State.objects.filter(project=project, group="completed").first()
        response = api_client.patch(
            queue_url(workspace, group, f"items/{issue.id}/"), {"state_id": str(done.id)}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # self assign
        response = api_client.post(queue_url(workspace, group, f"items/{issue.id}/assign/"))
        assert response.status_code == status.HTTP_200_OK, response.data
        assert IssueAssignee.objects.filter(issue=issue, assignee=engineer).exists()
        membership = ProjectMember.objects.get(project=project, member=engineer)
        assert (membership.role, membership.designation) == (5, "DevOps")
        devops = next(q for q in api_client.get(f"/api/workspaces/{workspace.slug}/queues/").data)
        assert devops["counts"]["mine"] == 1
        assert devops["counts"]["unassigned"] == 0

        # now they can change it and comment
        detail = api_client.get(queue_url(workspace, group, f"items/{issue.id}/")).data
        assert detail["can_edit"] is True
        assert done.id in [uuid.UUID(state["id"]) for state in detail["states"]]
        response = api_client.patch(
            queue_url(workspace, group, f"items/{issue.id}/"),
            {"state_id": str(done.id), "priority": "high"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        issue.refresh_from_db()
        assert (issue.state_id, issue.priority) == (done.id, "high")
        response = api_client.post(
            queue_url(workspace, group, f"items/{issue.id}/comments/"), {"comment": "Server is up"}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert IssueComment.objects.filter(issue=issue, actor=engineer).exists()
        counts = api_client.get(f"/api/workspaces/{workspace.slug}/queues/").data[0]["counts"]
        assert counts == {"open": 0, "unassigned": 0, "mine": 0, "done": 1}

    @pytest.mark.django_db
    def test_people_outside_the_group_cannot_see_the_queue(self, session_client, api_client, workspace, project):
        group = devops_group(session_client, workspace)
        outsider = workspace_user(workspace)
        issue = Issue.objects.create(name="Rotate keys", project=project, workspace=workspace)
        send(session_client, workspace, project, issue, group)

        api_client.force_authenticate(user=outsider)

        assert api_client.get(f"/api/workspaces/{workspace.slug}/queues/").data == []
        assert api_client.get(queue_url(workspace, group, "items/")).status_code == status.HTTP_403_FORBIDDEN
        response = api_client.post(queue_url(workspace, group, f"items/{issue.id}/assign/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_group_without_self_assign_right_is_read_only(self, session_client, api_client, workspace, project):
        group = devops_group(session_client, workspace)
        session_client.patch(
            f"/api/workspaces/{workspace.slug}/groups/{group.id}/", {"permissions": ["queue.view"]}, format="json"
        )
        viewer = workspace_user(workspace)
        add_to_group(session_client, workspace, group, viewer)
        issue = Issue.objects.create(name="Backup DB", project=project, workspace=workspace)
        send(session_client, workspace, project, issue, group)

        api_client.force_authenticate(user=viewer)

        assert len(api_client.get(queue_url(workspace, group, "items/")).data) == 1
        response = api_client.post(queue_url(workspace, group, f"items/{issue.id}/assign/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_work_item_moves_between_queues_and_out(self, session_client, workspace, project):
        devops = devops_group(session_client, workspace)
        response = session_client.post(f"/api/workspaces/{workspace.slug}/groups/", {"name": "Security"}, format="json")
        security = WorkspaceGroup.objects.get(pk=response.data["id"])
        issue = Issue.objects.create(name="Pen test", project=project, workspace=workspace)

        send(session_client, workspace, project, issue, devops)
        send(session_client, workspace, project, issue, security)
        assert list(QueueItem.objects.filter(issue=issue).values_list("group_id", flat=True)) == [security.id]
        response = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/queue/"
        )
        assert response.data["group_name"] == "Security"

        send(session_client, workspace, project, issue, None)
        assert not QueueItem.objects.filter(issue=issue).exists()

    @pytest.mark.django_db
    def test_clients_cannot_send_to_a_queue(self, session_client, api_client, workspace, project):
        group = devops_group(session_client, workspace)
        client = workspace_user(workspace, role=5)
        ProjectMember.objects.create(project=project, workspace=workspace, member=client, role=5, designation="Client")
        issue = Issue.objects.create(name="Logo", project=project, workspace=workspace)

        api_client.force_authenticate(user=client)
        response = api_client.put(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/queue/",
            {"group_id": str(group.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
