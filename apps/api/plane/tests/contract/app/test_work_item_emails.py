# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Jira style notification emails, driven through the real API views and background tasks."""

import uuid
from unittest import mock

import pytest
from django.core import mail
from rest_framework import status

from plane.app.views.issue.unwatch import make_unwatch_token
from plane.bgtasks import email_notification_task, issue_activities_task, notification_task
from plane.bgtasks.email_notification_task import send_email_notification, stack_email_notification
from plane.utils.work_item_types import ensure_project_work_item_types
from plane.db.models import (
    Cycle,
    EmailNotificationLog,
    IssueSubscriber,
    Milestone,
    Notification,
    Project,
    ProjectMember,
    State,
    User,
    UserNotificationPreference,
    WorkspaceMember,
)

EMAIL_CONFIG = ("smtp.example.com", "apikey", "secret", "587", "1", "0", "Plane <no-reply@mail.example.com>")


@pytest.fixture
def run_tasks_inline():
    """Run the activity and notification tasks right away instead of through Celery."""
    patches = [
        mock.patch.object(
            issue_activities_task.issue_activity,
            "delay",
            side_effect=lambda **kwargs: issue_activities_task.issue_activity(**kwargs),
        ),
        mock.patch.object(
            notification_task.notifications,
            "delay",
            side_effect=lambda **kwargs: notification_task.notifications(**kwargs),
        ),
    ]
    for patch in patches:
        patch.start()
    yield
    for patch in patches:
        patch.stop()


def send_emails():
    """Run the per-minute email job and return the sent messages."""
    mail.outbox.clear()
    redis = mock.Mock()
    redis.get.return_value = b"https://app.example.com"
    with (
        mock.patch.object(email_notification_task, "redis_instance", return_value=redis),
        mock.patch.object(email_notification_task, "get_email_configuration", return_value=EMAIL_CONFIG),
        mock.patch.object(
            send_email_notification, "delay", side_effect=lambda **kwargs: send_email_notification(**kwargs)
        ),
    ):
        stack_email_notification()
    return list(mail.outbox)


def html_of(message):
    return message.alternatives[0][0]


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Sales", "identifier": "SALES"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


@pytest.fixture
def asha(workspace, project):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(
        email=f"asha-{suffix}@example.com",
        username=f"asha_{suffix}",
        first_name="Asha",
        last_name="Rao",
        display_name="asha",
        user_timezone="Asia/Kolkata",
    )
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=15)
    return user


def base_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}"


def create_item(session_client, workspace, project, **data):
    response = session_client.post(
        f"{base_url(workspace, project)}/issues/", {"name": "Login page", **data}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


@pytest.mark.contract
@pytest.mark.usefixtures("run_tasks_inline")
class TestWorkItemEmails:
    @pytest.mark.django_db
    def test_created_and_assigned_email(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])

        [message] = send_emails()

        key = f"SALES-{item['sequence_id']}"
        assert message.to == [asha.email]
        assert message.subject == f"[HLIS Flow] ({key}) Login page"
        html = html_of(message)
        assert f"Test User created {key} and assigned it to you" in html.replace("  ", " ") or (
            f"created {key} and assigned it to you" in html
        )
        assert "assigned to this work item" in html
        # the person who made the change never gets an email about it
        assert not EmailNotificationLog.objects.filter(receiver__email="user@plane.so").exists()

    @pytest.mark.django_db
    def test_assignment_email_is_sent_even_with_property_emails_off(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project)
        UserNotificationPreference.objects.filter(user=asha).update(property_change=False)

        session_client.patch(
            f"{base_url(workspace, project)}/issues/{item['id']}/", {"assignee_ids": [str(asha.id)]}, format="json"
        )

        [message] = send_emails()
        assert f"assigned SALES-{item['sequence_id']} to you" in html_of(message)

    @pytest.mark.django_db
    def test_comment_email_shows_the_comment(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])
        send_emails()

        session_client.post(
            f"{base_url(workspace, project)}/issues/{item['id']}/comments/",
            {"comment_html": "<p>Please check the <strong>API</strong></p><script>alert(1)</script>"},
            format="json",
        )

        [message] = send_emails()
        html = html_of(message)
        assert f"commented on SALES-{item['sequence_id']}" in html
        assert "Please check the <strong>API</strong>" in html
        assert "<script>" not in html
        # same subject as the first email, so mail clients keep one conversation per work item
        assert message.subject == f"[HLIS Flow] (SALES-{item['sequence_id']}) Login page"
        assert message.extra_headers["References"] == f"<work-item-{item['id']}@mail.example.com>"
        assert message.extra_headers["In-Reply-To"] == message.extra_headers["References"]

    @pytest.mark.django_db
    def test_mention_email(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project)

        session_client.post(
            f"{base_url(workspace, project)}/issues/{item['id']}/comments/",
            {
                "comment_html": f'<p>Hi <mention-component entity_identifier="{asha.id}" '
                'entity_name="user_mention"></mention-component> please review</p>'
            },
            format="json",
        )

        [message] = send_emails()
        html = html_of(message)
        assert f"mentioned you on SALES-{item['sequence_id']}" in html
        assert "Hi @asha please review" in html
        assert IssueSubscriber.objects.filter(issue_id=item["id"], subscriber=asha).exists()

    @pytest.mark.django_db
    def test_every_changed_field_is_listed(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])
        send_emails()
        parent = create_item(session_client, workspace, project, name="Auth")
        send_emails()
        started = State.objects.filter(project=project, group="started").first()
        milestone = Milestone.objects.create(name="Design signoff", project=project, workspace=workspace)
        feature_type = ensure_project_work_item_types(project)["feature"]

        response = session_client.patch(
            f"{base_url(workspace, project)}/issues/{item['id']}/",
            {
                "state_id": str(started.id),
                "priority": "high",
                "start_date": "2026-10-20",
                "target_date": "2026-10-30",
                "parent_id": parent["id"],
                "milestone_id": str(milestone.id),
                "type_id": str(feature_type.id),
                "name": "Login page v2",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT, response.data

        [message] = send_emails()
        html = html_of(message)
        for expected in [
            "Status",
            "In Progress",
            "Priority",
            "High",
            "Start date",
            "20 Oct 2026",
            "Due date",
            "30 Oct 2026",
            "Parent",
            f"SALES-{parent['sequence_id']}",
            "Milestone",
            "Design signoff",
            "Type",
            "Feature",
            "Login page v2",
        ]:
            assert expected in html, expected
        assert f"updated SALES-{item['sequence_id']}" in html

    @pytest.mark.django_db
    def test_sprint_change_is_listed(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])
        send_emails()
        sprint = Cycle.objects.create(name="SALES Sprint 1", project=project, workspace=workspace, owned_by=asha)

        session_client.post(
            f"{base_url(workspace, project)}/cycles/{sprint.id}/cycle-issues/", {"issues": [item["id"]]}, format="json"
        )

        [message] = send_emails()
        assert "Sprint" in html_of(message)
        assert "+ SALES Sprint 1" in html_of(message)

    @pytest.mark.django_db
    def test_times_are_in_the_recipients_timezone(self, session_client, workspace, project, asha):
        create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])
        log = EmailNotificationLog.objects.filter(receiver=asha).first()
        log.data["issue_activity"]["activity_time"] = "2026-10-16T09:30:00Z"
        log.save()
        EmailNotificationLog.objects.filter(receiver=asha).exclude(pk=log.pk).delete()

        [message] = send_emails()
        # 09:30 UTC is 3:00 PM in India
        assert "16 Oct 2026, 3:00 PM" in html_of(message)

    @pytest.mark.django_db
    def test_description_edit_is_one_email_line_and_no_inbox_entries(self, session_client, workspace, project, asha):
        item = create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])
        send_emails()
        inbox_before = Notification.objects.filter(receiver=asha).count()
        url = f"{base_url(workspace, project)}/issues/{item['id']}/"

        # the editor saves the description several times while typing
        for text in ["Build", "Build the", "Build the login form"]:
            session_client.patch(url, {"description_html": f"<p>{text}</p>"}, format="json")

        [message] = send_emails()
        assert html_of(message).count("updated the description") == 1
        assert Notification.objects.filter(receiver=asha).count() == inbox_before

    @pytest.mark.django_db
    def test_each_work_item_marks_only_its_own_logs_sent(self, session_client, workspace, project, asha):
        create_item(session_client, workspace, project, assignee_ids=[str(asha.id)])
        create_item(session_client, workspace, project, name="Signup page", assignee_ids=[str(asha.id)])

        messages = send_emails()

        assert len(messages) == 2
        assert not EmailNotificationLog.objects.filter(receiver=asha, sent_at__isnull=True).exists()


@pytest.mark.contract
class TestStopWatchingLink:
    @pytest.mark.django_db
    def test_link_asks_first_then_stops_watching(self, api_client, workspace, project, asha, session_client):
        item = create_item(session_client, workspace, project)
        IssueSubscriber.objects.create(issue_id=item["id"], project=project, subscriber=asha)
        url = f"/api/notifications/unwatch/{make_unwatch_token(asha.id, item['id'])}/"

        # opening the link (or a mail scanner opening it) changes nothing
        response = api_client.get(url)
        assert response.status_code == 200
        assert b"Stop watching" in response.content
        assert IssueSubscriber.objects.filter(issue_id=item["id"], subscriber=asha).exists()

        response = api_client.post(url)
        assert response.status_code == 200
        assert not IssueSubscriber.objects.filter(issue_id=item["id"], subscriber=asha).exists()

    @pytest.mark.django_db
    def test_tampered_link_is_rejected(self, api_client, workspace, project, asha, session_client):
        item = create_item(session_client, workspace, project)
        IssueSubscriber.objects.create(issue_id=item["id"], project=project, subscriber=asha)
        token = make_unwatch_token(asha.id, item["id"])

        response = api_client.post(f"/api/notifications/unwatch/{token[:-2]}xx/")

        assert response.status_code == 400
        assert IssueSubscriber.objects.filter(issue_id=item["id"], subscriber=asha).exists()
