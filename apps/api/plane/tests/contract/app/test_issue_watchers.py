# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework import status

from plane.bgtasks import email_notification_task
from plane.bgtasks.email_notification_task import send_email_notification, stack_email_notification
from plane.bgtasks.notification_task import notifications
from plane.db.models import (
    EmailNotificationLog,
    Issue,
    IssueSubscriber,
    Notification,
    Project,
    ProjectMember,
    User,
    UserNotificationPreference,
    WorkspaceMember,
)


def _create_project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Watchers", "identifier": "WAT"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def _member(workspace, project, name, is_project_member=True):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(
        email=f"{name}-{suffix}@example.com", username=f"{name}_{suffix}", first_name=name.title()
    )
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    if is_project_member:
        ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=15)
    return user


def _url(workspace, project, issue, path=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/{path}"


@pytest.fixture
def setup(session_client, workspace, create_user):
    project = _create_project(session_client, workspace)
    issue = Issue.objects.create(name="Login page", project=project, workspace=workspace)
    return project, issue


@pytest.mark.contract
class TestIssueWatchersApi:
    @pytest.mark.django_db
    def test_list_returns_only_the_watchers(self, session_client, workspace, setup):
        project, issue = setup
        watcher = _member(workspace, project, "asha")
        _member(workspace, project, "ravi")  # project member who does not watch
        IssueSubscriber.objects.create(issue=issue, project=project, subscriber=watcher)

        response = session_client.get(_url(workspace, project, issue, "issue-subscribers/"))

        assert response.status_code == status.HTTP_200_OK
        assert [row["subscriber"] for row in response.data] == [str(watcher.id)]

    @pytest.mark.django_db
    def test_add_other_members_as_watchers(self, session_client, workspace, setup):
        project, issue = setup
        asha = _member(workspace, project, "asha")
        ravi = _member(workspace, project, "ravi")

        response = session_client.post(
            _url(workspace, project, issue, "issue-subscribers/"),
            {"subscriber_ids": [str(asha.id), str(ravi.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert {row["subscriber"] for row in response.data} == {str(asha.id), str(ravi.id)}

        # adding someone who already watches is not an error and does not duplicate
        response = session_client.post(
            _url(workspace, project, issue, "issue-subscribers/"), {"subscriber": str(asha.id)}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert IssueSubscriber.objects.filter(issue=issue, subscriber=asha).count() == 1

    @pytest.mark.django_db
    def test_only_project_members_can_be_watchers(self, session_client, workspace, setup):
        project, issue = setup
        outsider = _member(workspace, project, "outsider", is_project_member=False)

        response = session_client.post(
            _url(workspace, project, issue, "issue-subscribers/"),
            {"subscriber_ids": [str(outsider.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["invalid_ids"] == [str(outsider.id)]

        response = session_client.post(
            _url(workspace, project, issue, "issue-subscribers/"), {"subscriber_ids": []}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not IssueSubscriber.objects.filter(issue=issue).exists()

    @pytest.mark.django_db
    def test_remove_watcher(self, session_client, workspace, setup):
        project, issue = setup
        asha = _member(workspace, project, "asha")
        IssueSubscriber.objects.create(issue=issue, project=project, subscriber=asha)

        url = _url(workspace, project, issue, f"issue-subscribers/{asha.id}/")
        assert session_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert not IssueSubscriber.objects.filter(issue=issue, subscriber=asha).exists()
        assert session_client.delete(url).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_watch_and_stop_watching_are_idempotent(self, session_client, workspace, setup, create_user):
        project, issue = setup
        url = _url(workspace, project, issue, "subscribe/")

        assert session_client.post(url).status_code == status.HTTP_201_CREATED
        assert session_client.post(url).status_code == status.HTTP_200_OK
        assert session_client.get(url).data == {"subscribed": True}

        assert session_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert session_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert session_client.get(url).data == {"subscribed": False}


def _comment_activity(issue, actor, comment_html="<p>Please check the login flow</p>"):
    return {
        "id": str(uuid.uuid4()),
        "verb": "created",
        "field": "comment",
        "actor_id": str(actor.id),
        "comment": "added a comment",
        "new_value": comment_html,
        "old_value": "",
        "issue_comment": str(uuid.uuid4()),
        "issue_detail": {"id": str(issue.id)},
        "new_identifier": None,
        "old_identifier": None,
        "created_at": timezone.now().isoformat(),
    }


def _notify(issue, project, actor, activities):
    notifications(
        type="comment.activity.created",
        issue_id=str(issue.id),
        project_id=str(project.id),
        actor_id=str(actor.id),
        subscriber=True,
        issue_activities_created=json.dumps(activities),
        requested_data=None,
        current_instance=None,
    )


@pytest.mark.contract
class TestWatcherCommentNotifications:
    @pytest.mark.django_db
    def test_every_watcher_except_the_commenter_is_notified(self, session_client, workspace, setup, create_user):
        project, issue = setup
        asha = _member(workspace, project, "asha")
        ravi = _member(workspace, project, "ravi")
        for user in (asha, ravi, create_user):
            IssueSubscriber.objects.create(issue=issue, project=project, subscriber=user)

        _notify(issue, project, create_user, [_comment_activity(issue, create_user)])

        logs = EmailNotificationLog.objects.filter(entity_identifier=issue.id)
        assert {log.receiver_id for log in logs} == {asha.id, ravi.id}
        assert all(log.data["issue_activity"]["field"] == "comment" for log in logs)
        assert set(Notification.objects.filter(entity_identifier=issue.id).values_list("receiver_id", flat=True)) == {
            asha.id,
            ravi.id,
        }

    @pytest.mark.django_db
    def test_comment_email_follows_the_comment_preference(self, session_client, workspace, setup, create_user):
        project, issue = setup
        asha = _member(workspace, project, "asha")
        IssueSubscriber.objects.create(issue=issue, project=project, subscriber=asha)
        # comments switched off, other property changes still on
        UserNotificationPreference.objects.filter(user=asha).update(comment=False, property_change=True)

        _notify(issue, project, create_user, [_comment_activity(issue, create_user)])

        assert not EmailNotificationLog.objects.filter(receiver=asha).exists()
        # still shown in the in-app inbox
        assert Notification.objects.filter(receiver=asha, entity_identifier=issue.id).exists()

    @pytest.mark.django_db
    def test_watcher_without_preference_row_is_still_notified(self, session_client, workspace, setup, create_user):
        project, issue = setup
        asha = _member(workspace, project, "asha")
        ravi = _member(workspace, project, "ravi")
        for user in (asha, ravi):
            IssueSubscriber.objects.create(issue=issue, project=project, subscriber=user)
        UserNotificationPreference.objects.filter(user=asha).delete()

        _notify(issue, project, create_user, [_comment_activity(issue, create_user)])

        assert set(EmailNotificationLog.objects.values_list("receiver_id", flat=True)) == {asha.id, ravi.id}

    @pytest.mark.django_db
    def test_comment_email_is_sent_to_each_watcher(self, session_client, workspace, setup, create_user):
        project, issue = setup
        asha = _member(workspace, project, "asha")
        ravi = _member(workspace, project, "ravi")
        for user in (asha, ravi):
            IssueSubscriber.objects.create(issue=issue, project=project, subscriber=user)
        _notify(issue, project, create_user, [_comment_activity(issue, create_user)])

        redis = mock.Mock()
        redis.get.return_value = b"https://plane.example.com"
        email_config = ("smtp.example.com", "apikey", "secret", "587", "1", "0", "Plane <no-reply@example.com>")
        with (
            mock.patch.object(email_notification_task, "redis_instance", return_value=redis),
            mock.patch.object(email_notification_task, "get_email_configuration", return_value=email_config),
            mock.patch.object(
                send_email_notification, "delay", side_effect=lambda **kwargs: send_email_notification(**kwargs)
            ),
        ):
            stack_email_notification()

        assert sorted(message.to[0] for message in mail.outbox) == sorted([asha.email, ravi.email])
        message = mail.outbox[0]
        assert message.subject == f"[Hlink Sprint] (WAT-{issue.sequence_id}) Login page"
        html = message.alternatives[0][0]
        assert "Please check the login flow" in html
        assert f"commented on WAT-{issue.sequence_id}" in html
        assert not EmailNotificationLog.objects.filter(processed_at__isnull=True).exists()

    @pytest.mark.django_db
    def test_comment_email_uses_app_url_when_request_origin_is_missing(
        self, session_client, workspace, setup, create_user, settings
    ):
        """Comments made through the public API carry no request origin; watchers must still get the email."""
        project, issue = setup
        asha = _member(workspace, project, "asha")
        IssueSubscriber.objects.create(issue=issue, project=project, subscriber=asha)
        _notify(issue, project, create_user, [_comment_activity(issue, create_user)])
        settings.APP_BASE_URL = "https://app.example.com/"

        redis = mock.Mock()
        redis.get.return_value = None
        email_config = ("smtp.example.com", "apikey", "secret", "587", "1", "0", "Plane <no-reply@example.com>")
        with (
            mock.patch.object(email_notification_task, "redis_instance", return_value=redis),
            mock.patch.object(email_notification_task, "get_email_configuration", return_value=email_config),
            mock.patch.object(
                send_email_notification, "delay", side_effect=lambda **kwargs: send_email_notification(**kwargs)
            ),
        ):
            stack_email_notification()

        assert [message.to for message in mail.outbox] == [[asha.email]]
        assert (
            f"https://app.example.com/{workspace.slug}/projects/{project.id}/issues/{issue.id}"
            in (mail.outbox[0].alternatives[0][0])
        )
