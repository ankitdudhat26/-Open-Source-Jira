# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""External read-only API (/api/ext/v1/): log in with email and password, list My Projects, a project's work items
and a work item's full details. It has its own sessions, so the app's API tokens are not touched."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import (
    APIToken,
    ExternalApiSession,
    FileAsset,
    Intake,
    IntakeIssue,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLink,
    IssueRelation,
    IssueSubscriber,
    Label,
    IssueLabel,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)

BASE = "/api/ext/v1/"
PASSWORD = "Str0ng!Passw0rd#2026"


def _clear_api_limits():
    # only this API's own keys (login/request limits and failed-login counters), not the whole cache
    for pattern in ("*throttle_ext_api*", "*ext_api_login_fail:*"):
        cache.delete_pattern(pattern)


@pytest.fixture(autouse=True)
def clear_throttles():
    _clear_api_limits()
    yield
    _clear_api_limits()


def person(workspace, name, role=15, password=PASSWORD):
    user = User.objects.create(
        email=f"{name}-{uuid4().hex[:6]}@example.com",
        username=f"{name}_{uuid4().hex[:6]}",
        first_name=name.title(),
        last_name="Test",
    )
    user.set_password(password)
    user.save()
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


def project_with(workspace, owner, name, identifier, members=()):
    project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=owner)
    for user, role in members:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    states = {}
    for index, (state_name, group) in enumerate(
        [("To Do", "unstarted"), ("In Progress", "started"), ("In QA", "started"), ("Done", "completed")]
    ):
        states[state_name] = State.objects.create(
            name=state_name, group=group, project=project, workspace=workspace, sequence=index, default=index == 0
        )
    return project, states


def login(user):
    client = APIClient()
    response = client.post(f"{BASE}auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert response.status_code == 200, response.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['token']}")
    return client, response.data


@pytest.fixture
def world(db, workspace, create_user):
    dev = person(workspace, "rajendra")
    other = person(workspace, "keval")
    zydus, states = project_with(workspace, create_user, "Zydus DMS Support", "ZYD", [(dev, 20), (other, 15)])
    sales, _ = project_with(workspace, create_user, "Sales Pilot", "SAL", [(dev, 15)])
    hidden, hidden_states = project_with(workspace, create_user, "Not mine", "NOT", [(other, 20)])
    archived, _ = project_with(workspace, create_user, "Old one", "OLD", [(dev, 20)])
    Project.objects.filter(pk=archived.pk).update(archived_at=timezone.now())
    left, _ = project_with(workspace, create_user, "Left it", "LFT", [(dev, 20)])
    ProjectMember.objects.filter(project=left, member=dev).update(is_active=False)

    items = {}
    for name, state_name in [
        ("E-mail notification for transactions", "In Progress"),
        ("Dc-gow-0454 Nextgen Issue", "Done"),
        ("ARS PO NOT WORKING", "Done"),
        ("pdf print proper required", "To Do"),
    ]:
        items[name] = Issue.objects.create(name=name, project=zydus, workspace=workspace, state=states[state_name])
    # not listed: a draft, an archived one and a request still waiting in Intake
    Issue.objects.create(name="draft", project=zydus, workspace=workspace, state=states["To Do"], is_draft=True)
    Issue.objects.create(
        name="archived", project=zydus, workspace=workspace, state=states["Done"], archived_at=timezone.now()
    )
    foreign = Issue.objects.create(name="secret", project=hidden, workspace=workspace, state=hidden_states["To Do"])
    return {
        "dev": dev,
        "other": other,
        "zydus": zydus,
        "sales": sales,
        "hidden": hidden,
        "states": states,
        "items": items,
        "foreign": foreign,
    }


@pytest.mark.contract
class TestLogin:
    @pytest.mark.django_db
    def test_login_returns_a_bearer_token_and_keeps_only_its_hash(self, world):
        tokens_before = APIToken.objects.count()
        _, data = login(world["dev"])

        assert data["token_type"] == "Bearer" and data["token"].startswith("hlx_")
        assert data["user"]["email"] == world["dev"].email
        session = ExternalApiSession.objects.get(user=world["dev"])
        assert data["token"] not in (session.token_hash, session.token_hint)
        # the app's API tokens (Settings → API tokens) are not touched
        assert APIToken.objects.count() == tokens_before

    @pytest.mark.django_db
    def test_wrong_password_and_unknown_email_get_the_same_answer(self, world):
        client = APIClient()
        wrong = client.post(f"{BASE}auth/login/", {"email": world["dev"].email, "password": "nope"}, format="json")
        unknown = client.post(f"{BASE}auth/login/", {"email": "who@example.com", "password": "x"}, format="json")
        missing = client.post(f"{BASE}auth/login/", {"email": world["dev"].email}, format="json")

        assert (wrong.status_code, wrong.data["code"]) == (401, "INVALID_CREDENTIALS")
        assert (unknown.status_code, unknown.data["code"]) == (401, "INVALID_CREDENTIALS")
        assert wrong.data["error"] == unknown.data["error"]
        assert (missing.status_code, missing.data["code"]) == (400, "MISSING_CREDENTIALS")

    @pytest.mark.django_db
    def test_bots_and_deactivated_users_cannot_log_in(self, world):
        User.objects.filter(pk=world["other"].pk).update(is_bot=True)
        client = APIClient()
        response = client.post(
            f"{BASE}auth/login/", {"email": world["other"].email, "password": PASSWORD}, format="json"
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_logins_are_throttled(self, world):
        client = APIClient()
        codes = [
            client.post(f"{BASE}auth/login/", {"email": world["dev"].email, "password": "x"}, format="json").status_code
            for _ in range(11)
        ]
        assert codes[:10] == [401] * 10 and codes[10] == 429


@pytest.mark.contract
class TestToken:
    @pytest.mark.django_db
    def test_requests_need_a_valid_token(self, world):
        anonymous = APIClient().get(f"{BASE}projects/")
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION="Bearer hlx_not-a-real-token")

        assert anonymous.status_code == 401
        assert bad.get(f"{BASE}projects/").status_code == 401

    @pytest.mark.django_db
    def test_logout_and_expiry_end_the_session(self, world):
        client, _ = login(world["dev"])
        assert client.get(f"{BASE}me/").data["email"] == world["dev"].email
        assert client.post(f"{BASE}auth/logout/").status_code == 204
        assert client.get(f"{BASE}me/").status_code == 401

        client, _ = login(world["dev"])
        ExternalApiSession.objects.filter(user=world["dev"], revoked_at__isnull=True).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        assert client.get(f"{BASE}me/").status_code == 401

    @pytest.mark.django_db
    def test_a_session_cookie_is_not_enough(self, world):
        # being logged in to the app in a browser does not open this API: it only takes the Bearer token
        from django.test import Client

        browser = Client()
        browser.force_login(world["dev"])
        assert browser.get(f"{BASE}projects/").status_code == 401


@pytest.mark.contract
class TestProjects:
    @pytest.mark.django_db
    def test_lists_my_projects_only(self, world):
        client, _ = login(world["dev"])
        data = client.get(f"{BASE}projects/").data

        assert data["count"] == 2
        assert [(p["name"], p["identifier"], p["your_role"]) for p in data["results"]] == [
            ("Sales Pilot", "SAL", "member"),
            ("Zydus DMS Support", "ZYD", "admin"),
        ]
        assert data["results"][1]["id"] == str(world["zydus"].id)
        assert client.get(f"{BASE}projects/", {"search": "zyd"}).data["count"] == 1

    @pytest.mark.django_db
    def test_leaving_the_workspace_hides_its_projects(self, world):
        WorkspaceMember.objects.filter(member=world["dev"]).update(is_active=False)
        client, _ = login(world["dev"])
        assert client.get(f"{BASE}projects/").data["count"] == 0


@pytest.mark.contract
class TestWorkItems:
    @pytest.mark.django_db
    def test_lists_every_status_like_the_work_items_screen(self, world):
        client, _ = login(world["dev"])
        data = client.get(f"{BASE}projects/{world['zydus'].id}/work-items/").data

        assert data["count"] == 4
        assert sorted(row["state"]["name"] for row in data["results"]) == ["Done", "Done", "In Progress", "To Do"]
        row = next(r for r in data["results"] if r["name"] == "E-mail notification for transactions")
        for key in [
            "id",
            "key",
            "type",
            "state",
            "priority",
            "assignees",
            "labels",
            "modules",
            "sprint",
            "start_date",
            "due_date",
            "estimate",
            "parent",
            "milestone",
            "created_by",
            "created_at",
            "updated_at",
        ]:
            assert key in row
        assert row["key"].startswith("ZYD-")

    @pytest.mark.django_db
    def test_pagination_and_filters(self, world):
        client, _ = login(world["dev"])
        url = f"{BASE}projects/{world['zydus'].id}/work-items/"
        first = client.get(url, {"per_page": 3}).data
        second = client.get(url, {"per_page": 3, "page": 2}).data
        done = client.get(url, {"state_group": "completed"}).data
        found = client.get(url, {"search": "ars po"}).data

        assert (first["total_pages"], first["next_page"], len(first["results"])) == (2, 2, 3)
        assert (second["next_page"], len(second["results"])) == (None, 1)
        assert done["count"] == 2
        assert [r["name"] for r in found["results"]] == ["ARS PO NOT WORKING"]
        assert client.get(url, {"page": "x"}).status_code == 400

    @pytest.mark.django_db
    def test_projects_you_are_not_in_are_not_found(self, world):
        client, _ = login(world["dev"])
        assert client.get(f"{BASE}projects/{world['hidden'].id}/work-items/").status_code == 404
        assert client.get(f"{BASE}projects/{uuid4()}/work-items/").status_code == 404
        assert client.get(f"{BASE}work-items/{world['foreign'].id}/").status_code == 404

    @pytest.mark.django_db
    def test_a_guest_of_a_project_that_hides_the_rest_sees_only_their_own(self, world, workspace):
        guest = person(workspace, "client", role=5)
        ProjectMember.objects.create(project=world["zydus"], member=guest, workspace=workspace, role=5)
        Project.objects.filter(pk=world["zydus"].pk).update(guest_view_all_features=False)
        mine = Issue.objects.create(
            name="mine", project=world["zydus"], workspace=workspace, state=world["states"]["To Do"]
        )
        Issue.objects.filter(pk=mine.pk).update(created_by=guest)
        client, _ = login(guest)

        listed = client.get(f"{BASE}projects/{world['zydus'].id}/work-items/").data
        assert [row["name"] for row in listed["results"]] == ["mine"]
        other_item = world["items"]["ARS PO NOT WORKING"]
        assert client.get(f"{BASE}work-items/{other_item.id}/").status_code == 404


@pytest.mark.contract
class TestWorkItemDetail:
    @pytest.mark.django_db
    def test_has_everything_the_work_item_screen_shows(self, world, workspace):
        dev = world["dev"]
        issue = world["items"]["E-mail notification for transactions"]
        Issue.objects.filter(pk=issue.pk).update(
            description_html="<p>Whenever shine is doing any transaction</p>",
            description_stripped="Whenever shine is doing any transaction",
            priority="high",
        )
        IssueAssignee.objects.create(issue=issue, assignee=dev, project=world["zydus"], workspace=workspace)
        IssueSubscriber.objects.create(issue=issue, subscriber=dev, project=world["zydus"], workspace=workspace)
        label = Label.objects.create(
            name="Salesforce Developer", color="#F59E0B", project=world["zydus"], workspace=workspace
        )
        IssueLabel.objects.create(issue=issue, label=label, project=world["zydus"], workspace=workspace)
        child = Issue.objects.create(
            name="Fix SMTP", project=world["zydus"], workspace=workspace, state=world["states"]["To Do"], parent=issue
        )
        IssueRelation.objects.create(
            issue=issue,
            related_issue=world["items"]["ARS PO NOT WORKING"],
            relation_type="blocked_by",
            project=world["zydus"],
            workspace=workspace,
        )
        IssueLink.objects.create(
            issue=issue, url="https://example.com", title="Spec", project=world["zydus"], workspace=workspace
        )
        IssueComment.objects.create(
            issue=issue, actor=dev, comment_html="<p>Looking into it</p>", project=world["zydus"], workspace=workspace
        )
        IssueActivity.objects.create(
            issue=issue,
            actor=dev,
            verb="updated",
            field="state",
            old_value="To Do",
            new_value="In Progress",
            project=world["zydus"],
            workspace=workspace,
        )
        FileAsset.objects.create(
            attributes={"name": "mail body.png", "type": "image/png", "size": 55000},
            asset="ws/mail-body.png",
            size=55000,
            workspace=workspace,
            project=world["zydus"],
            issue=issue,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            is_uploaded=True,
        )
        intake = Intake.objects.create(name="Intake", project=world["zydus"], is_default=True)
        IntakeIssue.objects.create(
            intake=intake,
            issue=issue,
            project=world["zydus"],
            workspace=workspace,
            status=1,
            source_email="manish@zydus.com",
        )
        client, _ = login(dev)

        with patch("plane.ext_api.views.S3Storage") as storage:
            storage.return_value.generate_presigned_url.return_value = "https://files.test/mail-body.png"
            response = client.get(f"{BASE}work-items/{issue.id}/")

        assert response.status_code == 200, response.data
        data = response.data
        assert data["project"]["name"] == "Zydus DMS Support"
        assert data["description_text"] == "Whenever shine is doing any transaction"
        assert (data["state"]["name"], data["priority"], data["priority_label"]) == ("In Progress", "high", "High")
        assert [a["email"] for a in data["assignees"]] == [dev.email]
        assert [w["email"] for w in data["watchers"]] == [dev.email]
        assert [label["name"] for label in data["labels"]] == ["Salesforce Developer"]
        assert [c["name"] for c in data["sub_work_items"]] == ["Fix SMTP"] and child
        assert data["relations"][0]["relation_type"] == "blocked_by"
        assert data["relations"][0]["work_item"]["name"] == "ARS PO NOT WORKING"
        assert data["links"][0]["url"] == "https://example.com"
        assert data["attachments"][0]["name"] == "mail body.png"
        assert data["attachments"][0]["url"] == "https://files.test/mail-body.png"
        assert data["comments"][0]["comment_html"] == "<p>Looking into it</p>"
        assert data["activity"][0]["field"] == "state" and data["activity"][0]["new_value"] == "In Progress"
        assert data["intake"]["status"] == "accepted"
        for key in ["custom_fields", "queues", "reactions", "estimate", "milestone", "sprint", "modules"]:
            assert key in data

    @pytest.mark.django_db
    def test_unknown_or_malformed_ids_are_not_found(self, world):
        client, _ = login(world["dev"])
        assert client.get(f"{BASE}work-items/{uuid4()}/").status_code == 404


@pytest.mark.contract
class TestReviewFixes:
    @pytest.mark.django_db
    def test_password_sign_in_turned_off_on_the_instance_applies_here(self, world):
        with patch("plane.ext_api.views.get_configuration_value", return_value=("0",)):
            response = APIClient().post(
                f"{BASE}auth/login/", {"email": world["dev"].email, "password": PASSWORD}, format="json"
            )
        assert (response.status_code, response.data["code"]) == (403, "PASSWORD_LOGIN_DISABLED")

    @pytest.mark.django_db
    def test_a_made_up_forwarded_for_does_not_get_around_the_limit(self, world):
        client = APIClient()
        codes = [
            client.post(
                f"{BASE}auth/login/",
                {"email": f"nobody{n}@example.com", "password": "x"},
                format="json",
                # the client sends anything first; the proxy appends the real address last
                HTTP_X_FORWARDED_FOR=f"10.0.0.{n}, 203.0.113.7",
            ).status_code
            for n in range(11)
        ]
        assert codes[10] == 429

    @pytest.mark.django_db
    def test_too_many_wrong_passwords_lock_the_account_whatever_the_address(self, world):
        email = world["dev"].email
        for n in range(10):
            APIClient().post(
                f"{BASE}auth/login/",
                {"email": email, "password": "wrong"},
                format="json",
                REMOTE_ADDR=f"198.51.100.{n}",
            )
        locked = APIClient().post(
            f"{BASE}auth/login/", {"email": email, "password": PASSWORD}, format="json", REMOTE_ADDR="198.51.100.99"
        )
        assert (locked.status_code, locked.data["code"]) == (429, "TOO_MANY_FAILED_LOGINS")

    @pytest.mark.django_db
    def test_a_new_password_ends_the_tokens(self, world):
        client, _ = login(world["dev"])
        world["dev"].set_password("An0ther!Passw0rd#2026")
        world["dev"].save()
        assert client.get(f"{BASE}me/").status_code == 401

    @pytest.mark.django_db
    def test_details_follow_the_app(self, world, workspace):
        from plane.db.models import CustomField, CustomFieldValue

        dev, other = world["dev"], world["other"]
        issue = world["items"]["E-mail notification for transactions"]
        child = Issue.objects.create(
            name="Fix SMTP", project=world["zydus"], workspace=workspace, state=world["states"]["To Do"], parent=issue
        )
        # assignee changed from other to dev: the app keeps the old row, marked deleted
        old = IssueAssignee.objects.create(issue=child, assignee=other, project=world["zydus"], workspace=workspace)
        old.delete()
        IssueAssignee.objects.create(issue=child, assignee=dev, project=world["zydus"], workspace=workspace)
        for field_name in ["state", "vote", "reaction", "draft"]:
            IssueActivity.objects.create(
                issue=issue, actor=dev, verb="updated", field=field_name, project=world["zydus"], workspace=workspace
            )
        field = CustomField.objects.create(
            name="Reviewer", field_type="user", project=world["zydus"], workspace=workspace
        )
        CustomFieldValue.objects.create(
            issue=issue, field=field, value=[str(other.id)], project=world["zydus"], workspace=workspace
        )
        client, _ = login(dev)

        data = client.get(f"{BASE}work-items/{issue.id}/").data

        assert [a["email"] for a in data["sub_work_items"][0]["assignees"]] == [dev.email]
        assert [a["field"] for a in data["activity"]] == ["state"]
        assert data["custom_fields"][0]["value"][0]["email"] == other.email
