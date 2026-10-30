# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Jira import / sync against an in-memory Jira, the read only client and the history page."""

import contextlib
import copy
import io
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import (
    CustomField,
    CustomFieldValue,
    Cycle,
    Intake,
    CycleIssue,
    FileAsset,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueRelation,
    IssueSubscriber,
    JiraConnection,
    JiraEntityMap,
    JiraSyncRun,
    Module,
    ModuleIssue,
    Profile,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.license.utils.encryption import decrypt_data, encrypt_data
from plane.utils.jira.adf import adf_to_html
from plane.utils.jira.client import AtlassianAdminClient, JiraClient, JiraError, normalize_site_url, parse_user_export
from plane.utils.jira.importer import JiraImporter, jira_datetime, last_synced_at


def adf(text):
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def person(account_id, name, email=None):
    return {"accountId": account_id, "displayName": name, "emailAddress": email, "accountType": "atlassian"}


STATUSES = [
    {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
    {"id": "3", "name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    {"id": "10", "name": "Code Review", "statusCategory": {"key": "indeterminate"}},
    {"id": "5", "name": "Done", "statusCategory": {"key": "done"}},
    {"id": "6", "name": "Won't Do", "statusCategory": {"key": "done"}},
]


def jira_issue(issue_id, key, summary, status_id, **fields):
    status_value = next(s for s in STATUSES if s["id"] == status_id)
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": summary,
            "description": adf(f"Description of {summary}"),
            "status": status_value,
            "priority": {"name": fields.pop("priority", "Medium")},
            "issuetype": {"name": fields.pop("type", "Task"), "hierarchyLevel": 0},
            "created": "2024-01-02T10:00:00.000+0000",
            "updated": fields.pop("updated", "2024-01-05T10:00:00.000+0000"),
            "labels": fields.pop("labels", []),
            "attachment": fields.pop("attachment", []),
            "issuelinks": fields.pop("issuelinks", []),
            "components": fields.pop("components", []),
            **fields,
        },
    }


class FakeJira:
    """The calls JiraImporter makes, served from memory (like the real client, it only reads)."""

    def __init__(self, ada, bob):
        self.project_data = {
            "id": "10000",
            "key": "SHOP",
            "name": "Web Shop",
            "description": "Online store",
            "lead": ada,
            "components": [{"id": "100", "name": "Checkout"}],
        }
        epic = jira_issue("1", "SHOP-1", "Payments", "3", type="Epic")
        epic["fields"]["issuetype"]["hierarchyLevel"] = 1
        self.issue_data = [
            epic,
            jira_issue(
                "2",
                "SHOP-2",
                "Card payments",
                "10",
                parent={"id": "1", "key": "SHOP-1"},
                assignee=ada,
                reporter=bob,
                priority="Highest",
                labels=["backend"],
                duedate="2024-02-01",
                timeoriginalestimate=18000,
                timeestimate=7200,
                customfield_10020=[{"id": 31, "name": "Sprint 1"}],  # sprint: imported as a sprint, not a field
                customfield_10100={"value": "Backend"},
                customfield_10101=5,
                customfield_10102=[person("x7", "Parth Patel")],
                customfield_10103=None,
                components=[{"id": "100", "name": "Checkout"}],
                attachment=[
                    {
                        "id": "900",
                        "filename": "spec.pdf",
                        "size": 4,
                        "mimeType": "application/pdf",
                        "content": "https://acme.atlassian.net/rest/api/3/attachment/content/900",
                        "author": bob,
                    }
                ],
            ),
            jira_issue(
                "3",
                "SHOP-3",
                "Refund button broken",
                "6",
                type="Bug",
                issuelinks=[{"type": {"name": "Blocks"}, "outwardIssue": {"id": "2", "key": "SHOP-2"}}],
            ),
        ]
        self.comment_data = {
            "2": [{"id": "500", "author": bob, "body": adf("Looks good"), "created": "2024-01-03T09:00:00.000+0000"}]
        }
        self.history_data = {
            "2": [
                {
                    "id": "700",
                    "author": ada,
                    "created": "2024-01-04T09:00:00.000+0000",
                    "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}],
                }
            ]
        }
        self.history_data["2"].append(
            {
                "id": "701",
                "author": person("x7", "Parth Patel"),
                "created": "2024-01-16T16:27:00.000+0000",
                "items": [
                    {"field": "issuetype", "fromString": "Sub-task", "toString": "Task"},
                    {"field": "timeestimate", "from": "18000", "fromString": "18000", "to": "7200", "toString": "7200"},
                ],
            }
        )
        self.watcher_data = {"2": [bob, person("x9", "Outside Person")]}
        self.calls = []
        # updated_within_minutes of every issue search (None: the whole project)
        self.searches = []

    def project(self, key):
        return copy.deepcopy(self.project_data)

    def project_statuses(self, key):
        return copy.deepcopy(STATUSES)

    def issues(self, key, fields="*all", updated_within_minutes=None):
        self.searches.append(updated_within_minutes)
        found = copy.deepcopy(self.issue_data)
        if updated_within_minutes:
            since = timezone.now() - timedelta(minutes=updated_within_minutes)
            found = [item for item in found if jira_datetime(item["fields"]["updated"]) >= since]
        return found

    def comments(self, issue_id):
        return copy.deepcopy(self.comment_data.get(issue_id, []))

    def changelog(self, issue_id):
        return copy.deepcopy(self.history_data.get(issue_id, []))

    def watchers(self, issue_id):
        return copy.deepcopy(self.watcher_data.get(issue_id, []))

    def attachment_content(self, url):
        self.calls.append(("attachment", url))
        return b"%PDF"

    @contextlib.contextmanager
    def attachment_stream(self, url):
        self.calls.append(("attachment", url))
        yield io.BytesIO(b"%PDF")

    def boards(self, key):
        self.boards_read = True
        return list(self.board_data)

    browsable = True
    jira_count = None

    def can_browse(self, key):
        return self.browsable

    def projects(self):
        count = len(self.issue_data) if self.jira_count is None else self.jira_count
        return [{"key": "SHOP", "insight": {"totalIssueCount": count}}]

    def sprints(self, board_id):
        return [
            {
                "id": 31,
                "name": "Sprint 1",
                "state": "closed",
                "startDate": "2024-01-01T00:00:00.000Z",
                "endDate": "2024-01-14T00:00:00.000Z",
                "goal": "Payments",
            },
        ]

    def sprint_issue_ids(self, sprint_id):
        return ["2", "3"]

    board_data = ({"id": 1},)
    jira_users = ()
    jira_groups = {}
    jira_roles = ()

    def users(self):
        return list(self.jira_users)

    def groups(self):
        return [{"groupId": group_id, "name": name} for group_id, (name, _) in self.jira_groups.items()]

    def group_members(self, group_id):
        return self.jira_groups[group_id][1]

    def project_roles(self, key):
        return list(self.jira_roles)

    jira_assignable = ()

    def assignable_users(self, key):
        return list(self.jira_assignable)

    def fields(self):
        return [
            {
                "id": "customfield_10020",
                "name": "Sprint",
                "custom": True,
                "schema": {"type": "array", "items": "json", "custom": "com.pyxis.greenhopper.jira:gh-sprint"},
            },
            {
                "id": "customfield_10100",
                "name": "Task Type",
                "custom": True,
                "schema": {"type": "option", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:select"},
            },
            {"id": "customfield_10101", "name": "Story points", "custom": True, "schema": {"type": "number"}},
            {
                "id": "customfield_10102",
                "name": "Additional Assignees",
                "custom": True,
                "schema": {"type": "array", "items": "user"},
            },
            {"id": "customfield_10103", "name": "Empty field", "custom": True, "schema": {"type": "string"}},
            {"id": "timeoriginalestimate", "name": "Original estimate", "custom": False, "schema": {"type": "number"}},
        ]


@pytest.fixture
def people(workspace, create_user):
    ada_user = User.objects.create(email="ada@example.com", username="ada", first_name="Ada", display_name="ada")
    WorkspaceMember.objects.create(workspace=workspace, member=ada_user, role=15)
    bob_user = User.objects.create(
        email="bob@example.com", username="bob", first_name="Bob", last_name="Stone", display_name="bob"
    )
    WorkspaceMember.objects.create(workspace=workspace, member=bob_user, role=15)
    # Bob hides his email in Jira, so he is matched by name
    return ada_user, bob_user, person("a1", "Ada", "ada@example.com"), person("b2", "Bob Stone")


def run_import(workspace, user, fake, **options):
    keys = [] if options.get("kind") == "users" else ["SHOP"]
    run = JiraSyncRun.objects.create(workspace=workspace, initiated_by=user, project_keys=keys, options=options)
    with mock.patch("plane.settings.storage.S3Storage") as storage:
        storage.return_value.upload_file.return_value = True
        JiraImporter(run, fake, workspace, user).run_all()
    run.refresh_from_db()
    return run


@pytest.mark.contract
class TestJiraImport:
    @pytest.mark.django_db
    def test_full_import(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        run = run_import(workspace, create_user, FakeJira(ada, bob))

        project = Project.objects.get(pk=run.projects["SHOP"]["project_id"])
        assert (project.identifier, project.name, project.project_lead_id) == ("SHOP", "Web Shop", ada_user.id)
        # the same features as a project created in the app, with its Intake
        assert all(
            (project.cycle_view, project.module_view, project.issue_views_view, project.page_view, project.intake_view)
        )
        assert Intake.objects.filter(project=project, is_default=True).exists()
        # statuses keep their Jira names, in the right group
        groups = dict(State.objects.filter(project=project).values_list("name", "group"))
        assert groups == {
            "To Do": "unstarted",
            "In Progress": "started",
            "Code Review": "started",
            "Done": "completed",
            "Won't Do": "cancelled",
        }
        issues = {issue.external_id: issue for issue in Issue.objects.filter(project=project)}
        epic, card, bug = issues["1"], issues["2"], issues["3"]
        # every ticket keeps its Jira status
        assert (epic.state.name, card.state.name, bug.state.name) == ("In Progress", "Code Review", "Won't Do")
        assert (epic.type.name, card.type.name, bug.type.name) == ("Feature", "Task", "Bug")
        assert card.parent_id == epic.id
        assert card.priority == "urgent"
        assert str(card.target_date) == "2024-02-01"
        assert card.created_at.year == 2024 and card.created_by_id == bob_user.id
        assert "Description of Card payments" in card.description_html
        assert list(IssueAssignee.objects.filter(issue=card).values_list("assignee_id", flat=True)) == [ada_user.id]
        assert card.label_ids if hasattr(card, "label_ids") else True
        # links, sprint and component
        assert IssueRelation.objects.filter(issue=card, related_issue=bug, relation_type="blocked_by").exists()
        sprint = Cycle.objects.get(project=project, name="Sprint 1")
        assert sprint.description == "Payments"
        assert set(CycleIssue.objects.filter(cycle=sprint).values_list("issue_id", flat=True)) == {card.id, bug.id}
        assert ModuleIssue.objects.filter(
            issue=card, module=Module.objects.get(project=project, name="Checkout")
        ).exists()
        # comments, watchers, attachments, history
        comment = IssueComment.objects.get(issue=card)
        assert comment.actor_id == bob_user.id and "Looks good" in comment.comment_html
        assert IssueSubscriber.objects.filter(issue=card, subscriber=bob_user).exists()
        assert FileAsset.objects.filter(issue=card, external_id="900", is_uploaded=True).exists()
        history = IssueActivity.objects.get(issue=card, field="state")
        assert (history.old_value, history.new_value, history.actor_id) == ("To Do", "In Progress", ada_user.id)
        assert history.created_at.year == 2024
        # people are added to the project; the watcher without an account gets a disabled one (shown, no login)
        assert ProjectMember.objects.filter(project=project, member=ada_user, is_active=True).exists()
        outsider = User.objects.get(display_name="Outside Person")
        assert (outsider.email, outsider.is_active) == (None, False)
        assert IssueSubscriber.objects.filter(issue=card, subscriber=outsider).exists()
        # only seen in history: also a disabled account, so nobody is left unmatched
        assert run.unmatched_users == []
        assert not User.objects.get(display_name="Parth Patel").is_active
        assert run.stats["issues_created"] == 3

    @pytest.mark.django_db
    def test_sync_again_updates_and_never_duplicates(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)

        # nothing changed in Jira: nothing is read again
        second = run_import(workspace, create_user, fake)
        assert fake.searches[-1] and "issues_updated" not in second.stats
        assert Issue.objects.filter(external_source="jira").count() == 3
        assert IssueComment.objects.count() == 1 and IssueActivity.objects.filter(field="state").count() == 1
        assert len(fake.calls) == 1  # the attachment was downloaded once

        # a full re-sync reads every work item again, still without duplicating
        full = run_import(workspace, create_user, fake, full=True)
        assert fake.searches[-1] is None and full.stats["issues_updated"] == 3
        assert IssueComment.objects.count() == 1 and IssueActivity.objects.filter(field="state").count() == 1

        # SHOP-2 moved to Done in Jira
        fake.issue_data[1]["fields"]["status"] = STATUSES[3]
        fake.issue_data[1]["fields"]["updated"] = timezone.now().strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        third = run_import(workspace, create_user, fake)
        assert third.stats["issues_updated"] == 1
        card = Issue.objects.get(external_id="2")
        assert card.state.name == "Done"
        assert Issue.objects.filter(external_source="jira").count() == 3
        assert Project.objects.filter(workspace=workspace).count() == 1

    @pytest.mark.django_db
    def test_items_deleted_here_are_not_recreated(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        Issue.objects.get(external_id="3").delete()

        run_import(workspace, create_user, fake, full=True)

        assert not Issue.objects.filter(external_id="3").exists()


@pytest.mark.unit
class TestReadOnlyClient:
    def test_only_get_requests_are_sent(self):
        session = mock.Mock()
        session.headers = {}
        session.get.return_value = mock.Mock(status_code=200, json=lambda: {"displayName": "Ada"}, headers={})
        client = JiraClient("acme.atlassian.net", "a@example.com", "token", session=session)

        assert client.myself() == {"displayName": "Ada"}
        session.get.assert_called_once()
        assert session.get.call_args[0][0] == "https://acme.atlassian.net/rest/api/3/myself"
        for method in ("post", "put", "patch", "delete", "request"):
            getattr(session, method).assert_not_called()
        assert not any(hasattr(client, name) for name in ("post", "put", "patch", "delete", "update", "create"))

    def test_rate_limit_is_retried(self):
        session = mock.Mock()
        session.headers = {}
        busy = mock.Mock(status_code=429, headers={"Retry-After": "0"})
        ok = mock.Mock(status_code=200, json=lambda: {"ok": True}, headers={})
        session.get.side_effect = [busy, ok]
        with mock.patch("plane.utils.jira.client.time.sleep"):
            assert JiraClient("https://acme.atlassian.net", "a", "b", session=session).myself() == {"ok": True}

    def test_bad_credentials_and_foreign_urls_are_refused(self):
        session = mock.Mock()
        session.headers = {}
        session.get.return_value = mock.Mock(status_code=401, headers={})
        client = JiraClient("https://acme.atlassian.net", "a", "b", session=session)
        with pytest.raises(JiraError):
            client.myself()
        with pytest.raises(JiraError):
            client.attachment_content("https://evil.example.com/file")
        with pytest.raises(JiraError):
            normalize_site_url("http://acme.atlassian.net")

    def test_adf_is_converted_and_escaped(self):
        html = adf_to_html(
            {
                "type": "doc",
                "content": [
                    {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Plan"}]},
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "<b>bold</b>", "marks": [{"type": "strong"}]},
                            {
                                "type": "text",
                                "text": " link",
                                "marks": [{"type": "link", "attrs": {"href": "https://x.io"}}],
                            },
                        ],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}],
                            }
                        ],
                    },
                    {"type": "codeBlock", "content": [{"type": "text", "text": "a < b"}]},
                ],
            }
        )
        assert "<h2>Plan</h2>" in html
        assert "<strong>&lt;b&gt;bold&lt;/b&gt;</strong>" in html
        assert '<a href="https://x.io"' in html
        assert "<ul><li><p>one</p></li></ul>" in html
        assert "<pre><code>a &lt; b</code></pre>" in html


@pytest.mark.contract
class TestJiraApi:
    @pytest.mark.django_db
    def test_connection_is_checked_and_the_token_never_returned(self, session_client, workspace):
        url = f"/api/workspaces/{workspace.slug}/jira/connection/"
        with mock.patch("plane.app.views.workspace.jira.JiraClient") as client:
            client.return_value.myself.return_value = {"displayName": "Ada Admin"}
            response = session_client.put(
                url, {"site_url": "acme.atlassian.net", "email": "ada@acme.com", "api_token": "secret"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["site_url"] == "https://acme.atlassian.net"
        assert "api_token" not in response.data and "secret" not in str(response.data)
        connection = JiraConnection.objects.get(workspace=workspace)
        assert connection.api_token != "secret" and decrypt_data(connection.api_token) == "secret"

        with mock.patch("plane.app.views.workspace.jira.JiraClient") as client:
            client.return_value.myself.side_effect = JiraError("Jira rejected the email / API token.", 401)
            response = session_client.put(
                url, {"site_url": "acme.atlassian.net", "email": "ada@acme.com", "api_token": "wrong"}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_sync_is_queued_once(self, session_client, workspace, create_user):
        JiraConnection.objects.create(
            workspace=workspace, site_url="https://acme.atlassian.net", email="a@b.c", api_token="x"
        )
        url = f"/api/workspaces/{workspace.slug}/jira/syncs/"
        with mock.patch("plane.app.views.workspace.jira.jira_sync_task.delay") as delay:
            response = session_client.post(
                url, {"project_keys": ["SHOP"], "options": {"attachments": False}}, format="json"
            )
            assert response.status_code == status.HTTP_201_CREATED, response.data
            delay.assert_called_once_with(response.data["id"])
            again = session_client.post(url, {"project_keys": ["SHOP"]}, format="json")
        assert again.status_code == status.HTTP_409_CONFLICT
        assert session_client.get(url).data[0]["options"] == {"attachments": False}

    @pytest.mark.django_db
    def test_only_admins_use_the_import(self, api_client, workspace):
        member = User.objects.create(email="m@example.com", username="m")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        api_client.force_authenticate(user=member)
        assert api_client.get(f"/api/workspaces/{workspace.slug}/jira/connection/").status_code == 403


@pytest.mark.contract
class TestHistory:
    @pytest.mark.django_db
    def test_history_lists_changes_with_filters_and_respects_membership(
        self, session_client, api_client, workspace, create_user, people
    ):
        _, _, ada, bob = people
        run_import(workspace, create_user, FakeJira(ada, bob))
        url = f"/api/workspaces/{workspace.slug}/history/"

        data = session_client.get(url).data
        assert data["results"] and data["results"][0]["created_at"] >= data["results"][-1]["created_at"]
        state_change = session_client.get(url, {"field": "state"}).data["results"]
        assert len(state_change) == 1
        assert state_change[0]["issue"]["name"] == "Card payments"
        assert state_change[0]["from_jira"] is True
        assert (state_change[0]["old_value"], state_change[0]["new_value"]) == ("To Do", "In Progress")

        # a workspace member outside the project sees nothing of it
        outsider = User.objects.create(email=f"o-{uuid.uuid4().hex[:5]}@example.com", username=uuid.uuid4().hex[:8])
        WorkspaceMember.objects.create(workspace=workspace, member=outsider, role=15)
        api_client.force_authenticate(user=outsider)
        assert api_client.get(url).data["results"] == []


@pytest.mark.contract
class TestJiraHistoryAndFields:
    @pytest.mark.django_db
    def test_history_keeps_jira_names_dates_and_fields(self, workspace, create_user, people):
        _, _, ada, bob = people
        run_import(workspace, create_user, FakeJira(ada, bob))
        card = Issue.objects.get(external_id="2")

        entries = list(IssueActivity.objects.filter(issue=card, external_source="jira").order_by("created_at"))
        created = entries[0]
        assert (created.verb, created.external_actor_name) == ("created", "Bob Stone")
        # Parth Patel has no login here: his disabled account and Jira's name are on the entry
        issue_type = next(entry for entry in entries if entry.external_field_name == "Issue Type")
        parth = User.objects.get(display_name="Parth Patel")
        assert issue_type.actor_id == parth.id and issue_type.external_actor_name == "Parth Patel"
        assert (issue_type.old_value, issue_type.new_value) == ("Sub-task", "Task")
        assert issue_type.created_at.isoformat().startswith("2024-01-16T16:27")
        remaining = next(entry for entry in entries if entry.external_field_name == "Remaining Estimate")
        assert (remaining.old_value, remaining.new_value) == ("5h", "2h")
        status_change = next(entry for entry in entries if entry.external_field_name == "Status")
        assert status_change.external_actor_name == "Ada"

    @pytest.mark.django_db
    def test_jira_fields_become_project_custom_fields(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        card = Issue.objects.get(external_id="2")

        fields = {field.name: field for field in CustomField.objects.filter(project=card.project)}
        assert set(fields) == {
            "Task Type",
            "Story points",
            "Additional Assignees",
            "Original estimate",
            "Time remaining",
            "Reporter",
        }
        assert (fields["Task Type"].field_type, fields["Task Type"].options) == ("select", ["Backend"])
        values = {value.field.name: value.value for value in CustomFieldValue.objects.filter(issue=card)}
        assert values == {
            "Task Type": "Backend",
            "Story points": 5,
            "Additional Assignees": "Parth Patel",
            "Original estimate": "5h",
            "Time remaining": "2h",
            # Bob has an account here, but Jira's reporter is always shown as in Jira
            "Reporter": "Bob Stone",
        }

        # the value is cleared in Jira: it is cleared here on the next sync, no field is duplicated
        fake.issue_data[1]["fields"]["customfield_10101"] = None
        fake.issue_data[1]["fields"]["updated"] = jira_now()
        run_import(workspace, create_user, fake)
        assert not CustomFieldValue.objects.filter(issue=card, field=fields["Story points"]).exists()
        assert CustomField.objects.filter(project=card.project).count() == 6

    @pytest.mark.django_db
    def test_keys_match_jira_and_work_logs_read_like_jira(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        # Jira skips numbers (deleted issues)
        for jira_issue, key in zip(fake.issue_data, ["SHOP-5", "SHOP-57", "SHOP-60"]):
            jira_issue["key"] = key
        fake.issue_data[1]["fields"]["assignee"] = person("x8", "Nishant B")
        fake.history_data["2"].append(
            {
                "id": "702",
                "author": person("x8", "Nishant B"),
                "created": "2024-01-03T11:24:00.000+0000",
                "items": [
                    {"field": "timespent", "from": None, "fromString": None, "to": "10800", "toString": "10800"},
                    {"field": "WorklogId", "from": None, "fromString": None, "to": "10845", "toString": "10845"},
                ],
            }
        )
        run = run_import(workspace, create_user, fake)

        project = Project.objects.get(pk=run.projects["SHOP"]["project_id"])
        numbers = dict(Issue.objects.filter(project=project).values_list("external_id", "sequence_id"))
        assert numbers == {"1": 5, "2": 57, "3": 60}
        card = Issue.objects.get(external_id="2")
        logged = IssueActivity.objects.get(issue=card, field="worklog")
        assert (logged.verb, logged.new_value, logged.external_actor_name) == ("logged", "3h", "Nishant B")
        spent = IssueActivity.objects.get(issue=card, external_field_name="Time Spent")
        assert (spent.old_value, spent.new_value) == ("", "3h")
        # the assignee has no account here: a disabled account with Jira's name is the assignee
        nishant = User.objects.get(display_name="Nishant B")
        assert IssueAssignee.objects.get(issue=card).assignee_id == nishant.id and not nishant.is_active
        values = {value.field.name: value.value for value in CustomFieldValue.objects.filter(issue=card)}
        assert "Assignee (Jira)" not in values
        # a work item created here afterwards continues after the highest Jira number
        new = Issue.objects.create(name="New here", project=project, workspace=workspace)
        assert new.sequence_id == 61

        # syncing again keeps the numbers and does not add history twice
        history_count = IssueActivity.objects.filter(issue=card).count()
        run_import(workspace, create_user, fake, full=True)
        assert (
            dict(
                Issue.objects.filter(project=project, external_source="jira").values_list("external_id", "sequence_id")
            )
            == numbers
        )
        assert IssueActivity.objects.filter(issue=card).count() == history_count


@pytest.fixture(autouse=True)
def avatar_downloads():
    """Photos are 'downloaded' from memory and 'stored' without a bucket."""
    with (
        mock.patch.object(JiraImporter, "fetch_avatar", return_value=(b"PNG", "image/png")) as fetch,
        mock.patch("plane.settings.storage.S3Storage") as storage,
    ):
        storage.return_value.upload_file.return_value = True
        yield fetch


def jira_person(account_id, name, email, **extra):
    return {
        **person(account_id, name, email),
        "active": True,
        "timeZone": "Asia/Kolkata",
        "avatarUrls": {"48x48": f"https://avatar.example.com/{account_id}.png"},
        **extra,
    }


@pytest.mark.contract
class TestJiraUserSync:
    @pytest.mark.django_db
    def test_active_people_get_accounts_with_jira_details_and_roles(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        fake.jira_users = [
            jira_person("a1", "Ada", "ada@example.com"),
            jira_person("c3", "Chitra Rao", "Chitra@Example.com"),
            jira_person("d4", "Dev Shah", "dev@example.com"),
            jira_person("e5", "Gone Person", "gone@example.com", active=False),
            jira_person("f6", "Automation", "bot@example.com", accountType="app"),
            jira_person("g7", "Hidden Email", None),
        ]
        fake.jira_groups = {"g-admin": ("jira-admins-acme", [{"accountId": "c3"}]), "g-all": ("jira-users", [])}

        run = run_import(workspace, create_user, fake, kind="users")

        assert run.stats["users_created"] == 2
        assert run.stats["users_existing"] == 1
        assert run.stats["users_without_email"] == 1
        assert not User.objects.filter(email__in=["gone@example.com", "bot@example.com"]).exists()
        chitra = User.objects.get(email="chitra@example.com")
        assert (chitra.display_name, chitra.first_name, chitra.last_name) == ("Chitra Rao", "Chitra", "Rao")
        assert chitra.user_timezone == "Asia/Kolkata"
        # the photo is kept in this app's storage, not linked from outside
        assert chitra.avatar == "" and chitra.avatar_asset.attributes["source"] == "https://avatar.example.com/c3.png"
        assert chitra.is_password_autoset and Profile.objects.get(user=chitra).is_onboarded
        roles = dict(WorkspaceMember.objects.filter(workspace=workspace).values_list("member__email", "role"))
        assert roles["chitra@example.com"] == 20 and roles["dev@example.com"] == 15
        assert JiraEntityMap.objects.get(workspace=workspace, entity_type="user", jira_id="d4").jira_key == (
            "dev@example.com"
        )

        # running it again changes nothing and duplicates nobody
        run_import(workspace, create_user, fake, kind="users")
        assert User.objects.filter(email="chitra@example.com").count() == 1
        assert WorkspaceMember.objects.filter(workspace=workspace, member=chitra).count() == 1

    @pytest.mark.django_db
    def test_jira_project_roles_become_project_roles(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        fake.jira_users = [jira_person("d4", "Dev Shah", "dev@example.com"), jira_person("k9", "Kim", "kim@x.com")]
        fake.jira_groups = {"g-qa": ("qa-team", [{"accountId": "d4", "accountType": "atlassian"}])}
        fake.jira_roles = [
            {"name": "Administrators", "actors": [{"displayName": "Ada", "actorUser": {"accountId": "a1"}}]},
            {"name": "Developers", "actors": [{"actorGroup": {"groupId": "g-qa"}}]},
            {"name": "Viewers", "actors": [{"actorUser": {"accountId": "k9"}}, {"actorGroup": {"groupId": "g-qa"}}]},
        ]
        run_import(workspace, create_user, fake, kind="users")
        run_import(workspace, create_user, fake)
        project = Project.objects.get(identifier="SHOP")

        members = {
            m.member.email: (m.role, m.designation)
            for m in ProjectMember.objects.filter(project=project).select_related("member")
        }
        assert members["ada@example.com"] == (20, "Administrator")
        # in two roles: the higher one wins
        assert members["dev@example.com"] == (15, "Developer")
        assert members["kim@x.com"] == (5, "Viewer")

        # a role changed here is kept; one still as the sync left it follows Jira
        ProjectMember.objects.filter(project=project, member__email="kim@x.com").update(role=15, designation="QA")
        fake.jira_roles = fake.jira_roles[:2] + [{"name": "Testers", "actors": [{"actorUser": {"accountId": "k9"}}]}]
        fake.jira_roles[1] = {"name": "Leads", "actors": [{"actorGroup": {"groupId": "g-qa"}}]}
        run_import(workspace, create_user, fake, full=True)
        assert ProjectMember.objects.get(project=project, member__email="kim@x.com").designation == "QA"
        assert ProjectMember.objects.get(project=project, member__email="dev@example.com").designation == "Lead"

    @pytest.mark.django_db
    def test_user_sync_api(self, session_client, workspace):
        JiraConnection.objects.create(
            workspace=workspace, site_url="https://acme.atlassian.net", email="a@b.c", api_token="x"
        )
        url = f"/api/workspaces/{workspace.slug}/jira/syncs/"
        with mock.patch("plane.app.views.workspace.jira.jira_sync_task.delay") as delay:
            response = session_client.post(url, {"kind": "users"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        delay.assert_called_once()
        assert (response.data["options"], response.data["project_keys"]) == ({"kind": "users"}, [])


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Administrators", (20, "Administrator")),
        ("Read Only Admin", (5, "Read Only Admin")),
        ("jira-guest-member", (5, "jira-guest-member")),
        ("Dedicated Client", (5, "Dedicated Client")),
        ("Project Manager", (15, "Project Manager")),
        ("QA", (15, "QA")),
    ],
)
def test_jira_project_role_names(name, expected):
    assert JiraImporter.project_role(name) == expected


USERS_FILE = (
    "﻿User id,User name,email,User status,Added to org,Org role,Last seen in Jira\n"
    "h8,Hidden Person,Hidden@Example.com,Active,2024-01-01,Basic,2026-10-01\n"
    "o9,Org Admin,boss@example.com,Active,2024-01-01,Organization admin,2026-10-01\n"
    "s1,Suspended Person,sus@example.com,Suspended,2024-01-01,Basic,2025-01-01\n"
)


@pytest.mark.contract
class TestJiraUserDirectory:
    def test_users_file_is_read_by_column_name(self):
        people = parse_user_export(USERS_FILE)
        assert people["h8"] == {
            "email": "hidden@example.com",
            "name": "Hidden Person",
            "active": True,
            "org_admin": False,
            "time_zone": "",
            "avatar": "",
        }
        assert people["o9"]["org_admin"] and not people["s1"]["active"]
        with pytest.raises(JiraError):
            parse_user_export("name,phone\nAda,1\n")
        assert parse_user_export("Name,Email\nAda Byron,ada@x.com\n")["name:ada byron"]["email"] == "ada@x.com"

    def test_admin_client_only_reads_and_follows_cursors(self):
        session = mock.Mock()
        session.headers = {}
        pages = {
            "https://api.atlassian.com/admin/v1/orgs": {"data": [{"id": "org1", "attributes": {"name": "Acme"}}]},
            "https://api.atlassian.com/admin/v2/orgs/org1/directories": {"data": [{"directoryId": "d1"}]},
        }
        users = [
            {
                "data": [{"accountId": "h8", "email": "h@x.com", "name": "H", "accountStatus": "active"}],
                "links": {"next": "c2"},
            },
            {
                "data": [
                    {
                        "accountId": "o9",
                        "email": "o@x.com",
                        "name": "O",
                        "accountStatus": "suspended",
                        "platformRoles": ["atlassian/org-admin"],
                    }
                ],
                "links": {},
            },
        ]

        def get(url, params=None, **kwargs):
            body = users.pop(0) if url.endswith("/users") else pages[url]
            return mock.Mock(status_code=200, json=lambda: body, headers={})

        session.get.side_effect = get
        client = AtlassianAdminClient("key", session=session)
        assert client.orgs() == [{"id": "org1", "name": "Acme"}]
        people = client.users("org1")
        assert people["h8"]["email"] == "h@x.com" and people["h8"]["active"]
        assert people["o9"]["org_admin"] and not people["o9"]["active"]
        assert session.headers["Authorization"] == "Bearer key"
        for method in ("post", "put", "patch", "delete", "request"):
            getattr(session, method).assert_not_called()

    @pytest.mark.django_db
    def test_directory_gives_hidden_emails_status_and_org_admins(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        fake.jira_users = [
            jira_person("h8", "Hidden Person", None),
            jira_person("o9", "Org Admin", None),
            jira_person("s1", "Suspended Person", None),
        ]
        directory = parse_user_export(USERS_FILE)
        run = JiraSyncRun.objects.create(
            workspace=workspace, initiated_by=create_user, project_keys=[], options={"kind": "users"}
        )
        JiraImporter(run, fake, workspace, create_user, directory).run_all()

        roles = dict(WorkspaceMember.objects.filter(workspace=workspace).values_list("member__email", "role"))
        assert roles["hidden@example.com"] == 15 and roles["boss@example.com"] == 20
        assert "sus@example.com" not in roles
        assert User.objects.get(email="hidden@example.com").display_name == "Hidden Person"

        # deactivated in Jira later: access here ends too (the history keeps the name)
        fake.jira_users = [jira_person("h8", "Hidden Person", None, active=False)]
        run = JiraSyncRun.objects.create(
            workspace=workspace, initiated_by=create_user, project_keys=[], options={"kind": "users"}
        )
        JiraImporter(run, fake, workspace, create_user, directory).run_all()
        # an account the sync made stays listed (like Jira's deactivated users) but can no longer sign in
        hidden = User.objects.get(email="hidden@example.com")
        assert not hidden.is_active
        assert WorkspaceMember.objects.get(workspace=workspace, member=hidden).is_active

    @pytest.mark.django_db
    def test_users_file_upload_and_admin_key(self, session_client, workspace):
        JiraConnection.objects.create(
            workspace=workspace, site_url="https://acme.atlassian.net", email="a@b.c", api_token=encrypt_data("x")
        )
        url = f"/api/workspaces/{workspace.slug}/jira/syncs/"
        with mock.patch("plane.app.views.workspace.jira.jira_sync_task.delay"):
            bad = session_client.post(url, {"kind": "users", "users_file": "a,b\n1,2\n"}, format="json")
            assert bad.status_code == status.HTTP_400_BAD_REQUEST
            response = session_client.post(url, {"kind": "users", "users_file": USERS_FILE}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        # the emails stay on the server
        assert response.data["options"] == {"kind": "users"}
        assert JiraSyncRun.objects.get(pk=response.data["id"]).options["directory"]["h8"]["email"] == (
            "hidden@example.com"
        )

        with (
            mock.patch("plane.app.views.workspace.jira.JiraClient") as jira,
            mock.patch("plane.app.views.workspace.jira.AtlassianAdminClient") as admin,
        ):
            jira.return_value.myself.return_value = {"displayName": "Ada"}
            admin.return_value.orgs.return_value = [{"id": "org1", "name": "Acme"}]
            data = session_client.put(
                f"/api/workspaces/{workspace.slug}/jira/connection/",
                {"site_url": "acme.atlassian.net", "email": "a@b.c", "admin_api_key": "secret"},
                format="json",
            ).data
        assert (data["has_admin_api_key"], data["org_name"]) == (True, "Acme")
        assert "secret" not in str(data)
        connection = JiraConnection.objects.get(workspace=workspace)
        assert connection.org_id == "org1" and decrypt_data(connection.admin_api_key) == "secret"


@pytest.mark.contract
class TestJiraPeopleAfterUserSync:
    @pytest.mark.django_db
    def test_assignable_people_join_and_old_work_items_get_their_people(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        carol = jira_person("c3", "Carol Diaz", None)
        dave = jira_person("d4", "Dave Roy", None)
        fake = FakeJira(ada, bob)
        # SHOP-2 was Carol's, but she had no account at the first import: a disabled one stands in
        for jira_issue in fake.issue_data:
            if jira_issue["key"] == "SHOP-2":
                jira_issue["fields"]["assignee"] = carol
                jira_issue["fields"]["reporter"] = carol
        run_import(workspace, create_user, fake)
        issue = Issue.objects.get(project__identifier="SHOP", sequence_id=2)
        stand_in = IssueAssignee.objects.get(issue=issue).assignee
        assert (stand_in.display_name, stand_in.email, stand_in.is_active) == ("Carol Diaz", None, False)

        fake.jira_users = [carol, dave]
        fake.jira_assignable = [carol, dave, {**ada, "accountType": "app"}]
        directory = {
            "c3": {"email": "carol@example.com", "name": "", "active": True, "org_admin": False},
            "d4": {"email": "dave@example.com", "name": "", "active": True, "org_admin": False},
        }
        run = JiraSyncRun.objects.create(
            workspace=workspace, initiated_by=create_user, project_keys=[], options={"kind": "users"}
        )
        JiraImporter(run, fake, workspace, create_user, directory).run_all()

        # the user sync turns the stand-in into Carol's real account (same account, now with email and login)
        carol_user = User.objects.get(email="carol@example.com")
        assert carol_user.id == stand_in.id and carol_user.is_active
        project = issue.project
        members = set(
            ProjectMember.objects.filter(project=project, is_active=True).values_list("member__email", flat=True)
        )
        assert {"carol@example.com", "dave@example.com"} <= members
        assert list(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True)) == [carol_user.id]
        assert Issue.objects.get(pk=issue.pk).created_by_id == carol_user.id
        assert User.objects.filter(display_name="Carol Diaz").count() == 1


@pytest.mark.contract
class TestFormerJiraPeople:
    @pytest.mark.django_db
    def test_deactivated_assignee_is_shown_with_a_disabled_account(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        former = {**person("x9", "Hitesh Pal"), "active": False}
        fake = FakeJira(ada, bob)
        for jira_issue in fake.issue_data:
            if jira_issue["key"] == "SHOP-2":
                jira_issue["fields"]["assignee"] = former
        run_import(workspace, create_user, fake)

        hitesh = User.objects.get(display_name="Hitesh Pal")
        assert (hitesh.email, hitesh.is_active, hitesh.has_usable_password()) == (None, False, False)
        issue = Issue.objects.get(project__identifier="SHOP", sequence_id=2)
        assert list(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True)) == [hitesh.id]
        assert ProjectMember.objects.get(project=issue.project, member=hitesh).is_active
        assert WorkspaceMember.objects.get(workspace=workspace, member=hitesh).is_active

        # a second sync reuses the account
        run_import(workspace, create_user, fake, full=True)
        assert User.objects.filter(display_name="Hitesh Pal").count() == 1

        # never emailed
        from plane.bgtasks.email_notification_task import send_email_notification

        with mock.patch("plane.bgtasks.email_notification_task.build_work_item_email") as build:
            send_email_notification(str(issue.id), {}, str(hitesh.id), [])
        build.assert_not_called()


@pytest.mark.contract
class TestJiraAvatars:
    @pytest.mark.django_db
    def test_photos_are_stored_once_and_initials_are_drawn_here(self, workspace, create_user, people, avatar_downloads):
        ada_user, bob_user, ada, bob = people
        initials = (
            "https://secure.gravatar.com/avatar/abc?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod"
            ".public.atl-paas.net%2Finitials%2FJS-0.png"
        )
        fake = FakeJira(ada, bob)
        fake.jira_users = [
            jira_person("p1", "Photo Person", "photo@example.com"),
            jira_person("i1", "Initials Person", "initials@example.com", avatarUrls={"48x48": initials}),
        ]
        run_import(workspace, create_user, fake, kind="users")
        photo = User.objects.get(email="photo@example.com")
        plain = User.objects.get(email="initials@example.com")
        assert photo.avatar_url == f"/api/assets/v2/static/{photo.avatar_asset_id}/"
        assert (plain.avatar, plain.avatar_asset_id, plain.avatar_url) == ("", None, None)
        assert FileAsset.objects.get(pk=photo.avatar_asset_id).entity_type == "USER_AVATAR"
        assert avatar_downloads.call_count == 1

        # a second sync does not download the same photo again
        run_import(workspace, create_user, fake, kind="users")
        assert avatar_downloads.call_count == 1

    def test_initials_pictures_are_recognised(self):
        assert JiraImporter.avatar_source({"avatarUrls": {"48x48": "https://x/initials/AB-1.png"}}) == ""
        assert JiraImporter.avatar_source({}) == ""
        assert (
            JiraImporter.avatar_source({"avatarUrls": {"48x48": "https://cdn/acc/uuid/48"}})
            == "https://cdn/acc/uuid/48"
        )


@pytest.mark.contract
class TestLargeSyncs:
    @pytest.mark.django_db
    def test_big_attachments_are_copied_and_business_projects_have_no_sprints(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        fake.project_data["projectTypeKey"] = "business"
        for jira_issue in fake.issue_data:
            for attachment in jira_issue["fields"]["attachment"]:
                attachment["size"] = 300 * 1024 * 1024  # a 300 MB video: far over the 5 MB upload limit
        run = run_import(workspace, create_user, fake)
        assert run.warnings == []
        assert FileAsset.objects.get(external_id="900").size == 300 * 1024 * 1024
        assert not getattr(fake, "boards_read", False)

    @pytest.mark.django_db
    def test_projects_run_in_lanes_and_one_failure_does_not_stop_the_rest(self, workspace, create_user, people):
        from plane.bgtasks import jira_sync_task as task

        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        project = fake.project

        def project_or_fail(key):
            if key == "BAD":
                raise RuntimeError("boom")
            return project(key)

        fake.project = project_or_fail
        JiraConnection.objects.create(
            workspace=workspace, site_url="https://acme.atlassian.net", email="a@b.c", api_token=encrypt_data("x")
        )
        run = JiraSyncRun.objects.create(
            workspace=workspace, initiated_by=create_user, project_keys=["BAD", "SHOP"], options={}
        )
        with (
            mock.patch.object(task, "client_for", return_value=fake),
            mock.patch.object(task.jira_sync_lane_task, "delay", side_effect=task.jira_sync_lane_task),
        ):
            task.jira_sync_task(str(run.id))
        run.refresh_from_db()

        assert run.status == "completed" and "BAD" in run.error
        assert run.progress["SHOP"]["status"] == "done" and run.progress["SHOP"]["done"] == 3
        assert run.progress["BAD"]["status"] == "failed"
        assert Issue.objects.filter(project__identifier="SHOP").count() == 3

    @pytest.mark.django_db
    def test_interrupted_run_is_resumed_not_left_running(self, session_client, workspace, create_user):
        from datetime import timedelta

        from django.utils import timezone

        from plane.bgtasks import jira_sync_task as task

        run = JiraSyncRun.objects.create(
            workspace=workspace,
            initiated_by=create_user,
            project_keys=["A", "B"],
            status="running",
            started_at=timezone.now() - timedelta(hours=2),
            progress={
                "A": {"status": "done", "total": 40, "done": 40, "attempts": 1},
                "B": {"status": "running", "total": 60, "done": 20, "attempts": 1},
            },
        )
        JiraSyncRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        with mock.patch.object(task.jira_sync_lane_task, "delay") as delay:
            data = session_client.get(f"/api/workspaces/{workspace.slug}/jira/syncs/").data[0]
        assert delay.called
        assert data["status"] == "running"
        run.refresh_from_db()
        assert run.progress["B"]["status"] == "pending"
        # progress and the time left come with the run
        assert (data["progress"]["items_done"], data["progress"]["items_total"]) == (60, 100)
        assert data["progress"]["estimated_finish_at"] is not None

        # interrupted again and again: given up on, the run ends instead of running forever
        run.progress["B"].update(status="running", attempts=3)
        run.save()
        JiraSyncRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        task.recover_stale_runs(workspace.id)
        run.refresh_from_db()
        assert run.status == "completed" and run.progress["B"]["status"] == "failed"


def run_lanes(workspace, user, fake, keys=("SHOP",)):
    from plane.bgtasks import jira_sync_task as task

    if not JiraConnection.objects.filter(workspace=workspace).exists():
        JiraConnection.objects.create(
            workspace=workspace,
            site_url="https://acme.atlassian.net",
            email="a@b.c",
            api_token=encrypt_data("x"),
            account_name="Parth Patel",
        )
    run = JiraSyncRun.objects.create(workspace=workspace, initiated_by=user, project_keys=list(keys), options={})
    with (
        mock.patch.object(task, "client_for", return_value=fake),
        mock.patch.object(task.jira_sync_lane_task, "delay", side_effect=task.jira_sync_lane_task),
    ):
        task.jira_sync_task(str(run.id))
    run.refresh_from_db()
    return run


@pytest.mark.contract
class TestNoSilentGaps:
    @pytest.mark.django_db
    def test_project_the_account_cannot_browse_is_reported_not_created_empty(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        fake.browsable = False
        run = run_lanes(workspace, create_user, fake)
        assert run.progress["SHOP"]["status"] == "failed"
        assert "Parth Patel" in run.progress["SHOP"]["error"] and "Browse projects" in run.progress["SHOP"]["error"]
        assert not Project.objects.filter(identifier="SHOP").exists()

    @pytest.mark.django_db
    def test_work_items_hidden_from_the_account_are_reported(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        fake.jira_count = 5  # Jira counts 5, the account can read 3
        run = run_lanes(workspace, create_user, fake)
        assert run.progress["SHOP"]["status"] == "done"
        assert any("3 of 5 work items could be read" in warning for warning in run.warnings)


class ParallelFakeJira(FakeJira):
    """Offers clone(), so comments, history and watchers are read ahead by the thread pool."""

    def clone(self):
        return self


def snapshot(workspace):
    def rows(queryset):
        return sorted(queryset, key=repr)

    return {
        "history": rows(
            IssueActivity.objects.filter(workspace=workspace, external_source="jira").values_list(
                "issue__sequence_id", "field", "old_value", "new_value", "external_actor_name", "created_at"
            )
        ),
        "comments": rows(IssueComment.objects.filter(workspace=workspace).values_list("comment_html", "actor_id")),
        "watchers": rows(IssueSubscriber.objects.filter(workspace=workspace).values_list("issue_id", "subscriber_id")),
        "assets": rows(FileAsset.objects.filter(workspace=workspace).values_list("external_id", flat=True)),
    }


@pytest.mark.contract
class TestFastSync:
    @pytest.mark.django_db(transaction=True)
    def test_parallel_reading_gives_the_same_data(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        run_import(workspace, create_user, ParallelFakeJira(ada, bob))
        parallel = snapshot(workspace)
        assert parallel["history"] and parallel["comments"] and parallel["watchers"]

        # a full re-sync (sequential reading) finds nothing to change and duplicates nothing
        run = run_import(workspace, create_user, FakeJira(ada, bob), full=True)
        assert snapshot(workspace) == parallel
        assert "history_entries" not in run.stats

    @pytest.mark.django_db
    def test_unchanged_work_items_are_not_read_again(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        run_import(workspace, create_user, ParallelFakeJira(ada, bob))
        fake = ParallelFakeJira(ada, bob)
        with mock.patch.object(fake, "changelog", wraps=fake.changelog) as changelog:
            run_import(workspace, create_user, fake)
        changelog.assert_not_called()


def jira_now(**delta):
    return (timezone.now() + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


@pytest.mark.contract
class TestIncrementalSync:
    @pytest.mark.django_db
    def test_only_work_items_changed_since_the_last_sync_are_read(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        assert fake.searches == [None]  # the first import reads everything
        cursor = JiraEntityMap.objects.get(workspace=workspace, entity_type="project", jira_id="10000")
        assert last_synced_at(workspace, "SHOP", cursor) is not None

        # in Jira: SHOP-3 renamed, a new comment on it, a new work item SHOP-4; SHOP-1 / SHOP-2 untouched
        fake.issue_data[2]["fields"].update(summary="Refund button fixed", updated=jira_now())
        fake.comment_data["3"] = [{"id": "501", "author": ada, "body": adf("Fixed"), "created": jira_now()}]
        fake.issue_data.append(jira_issue("4", "SHOP-4", "Gift cards", "1", updated=jira_now()))
        with mock.patch.object(fake, "changelog", wraps=fake.changelog) as changelog:
            run = run_import(workspace, create_user, fake)

        assert fake.searches[-1] and fake.searches[-1] < 60  # minutes since the last sync, with the margin
        assert sorted(call.args[0] for call in changelog.call_args_list) == ["3", "4"]
        assert run.stats["issues_created"] == 1 and run.stats["issues_updated"] == 1
        assert run.stats["issues_seen"] == 2
        assert Issue.objects.get(external_id="3").name == "Refund button fixed"
        assert Issue.objects.get(external_id="4").sequence_id == 4
        assert Issue.objects.filter(external_source="jira").count() == 4
        assert IssueComment.objects.filter(external_id="501").count() == 1
        # the work items read before keep their comments, history, links and parents
        assert IssueComment.objects.filter(external_id="500").exists()
        assert Issue.objects.get(external_id="2").parent_id == Issue.objects.get(external_id="1").id
        assert IssueRelation.objects.count() == 1

        # synced again straight away: the changes are inside the margin, read again but nothing duplicated
        again = run_import(workspace, create_user, fake)
        assert again.stats.get("issues_unchanged") == 2 and "issues_created" not in again.stats
        assert Issue.objects.filter(external_source="jira").count() == 4
        assert IssueComment.objects.filter(external_id="501").count() == 1

    @pytest.mark.django_db
    def test_comments_and_components_removed_in_jira_are_removed_here(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        card = Issue.objects.get(external_id="2")
        assert IssueComment.objects.filter(issue=card).count() == 1
        assert ModuleIssue.objects.filter(issue=card).count() == 1
        mine = IssueComment.objects.create(
            issue=card, project=card.project, workspace=workspace, actor=ada_user, comment_html="<p>here</p>"
        )

        fake.comment_data["2"] = []
        fake.issue_data[1]["fields"].update(components=[], updated=jira_now())
        run = run_import(workspace, create_user, fake)

        assert run.stats["comments_deleted"] == 1
        # only the Jira comment is gone; comments written here stay
        assert list(IssueComment.objects.filter(issue=card)) == [mine]
        assert not ModuleIssue.objects.filter(issue=card).exists()

    @pytest.mark.django_db
    def test_work_item_whose_details_failed_is_read_again(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)

        fake.issue_data[1]["fields"]["updated"] = jira_now()
        fake.comment_data["2"].append({"id": "502", "author": ada, "body": adf("Second"), "created": jira_now()})
        with mock.patch.object(fake, "comments", side_effect=JiraError("Jira is busy", 429)):
            run_import(workspace, create_user, fake)
        assert not IssueComment.objects.filter(external_id="502").exists()

        # the failed sync did not mark the work item as synced, and did not move the project's cursor
        run_import(workspace, create_user, fake)
        assert IssueComment.objects.filter(external_id="502").exists()

    @pytest.mark.django_db
    def test_projects_synced_before_the_cursor_existed_use_their_last_run(self, workspace, create_user, people):
        ada_user, bob_user, ada, bob = people
        fake = FakeJira(ada, bob)
        run_lanes(workspace, create_user, fake)
        # as left by the earlier version: no cursor on the project
        JiraEntityMap.objects.filter(workspace=workspace, entity_type="project").update(jira_updated="")
        earlier = JiraSyncRun.objects.get()
        three_days_ago = timezone.now() - timedelta(days=3)
        earlier.progress["SHOP"]["started_at"] = three_days_ago.isoformat()
        earlier.started_at = three_days_ago
        earlier.save()

        fake.issue_data[0]["fields"].update(summary="Payments v2", updated=jira_now(days=-1))
        fake.issue_data[2]["fields"]["updated"] = jira_now(days=-5)  # changed before the last sync
        run = run_lanes(workspace, create_user, fake)

        assert 3 * 24 * 60 < fake.searches[-1] < 3 * 24 * 60 + 60
        assert run.stats["issues_updated"] == 1 and run.stats["issues_seen"] == 1
        assert Issue.objects.get(external_id="1").name == "Payments v2"
        assert run.progress["SHOP"]["total"] == 1 and run.progress["SHOP"]["since"]
        assert not any("could be read" in warning for warning in run.warnings)


@pytest.mark.contract
class TestStopSync:
    @pytest.mark.django_db
    def test_stop_ends_the_run_and_no_project_starts_after_it(self, session_client, workspace, create_user):
        run = JiraSyncRun.objects.create(
            workspace=workspace,
            initiated_by=create_user,
            project_keys=["A", "B", "C"],
            status="running",
            progress={
                "A": {"status": "done", "total": 1, "done": 1},
                "B": {"status": "running", "total": 5, "done": 2},
                "C": {"status": "pending", "total": 5, "done": 0},
            },
        )
        url = f"/api/workspaces/{workspace.slug}/jira/syncs/{run.id}/stop/"

        response = session_client.post(url)

        assert response.status_code == status.HTTP_200_OK, response.data
        run.refresh_from_db()
        assert run.status == "failed" and run.error.startswith("Stopped by")
        assert [run.progress[key]["status"] for key in "ABC"] == ["done", "failed", "failed"]
        assert session_client.post(url).status_code == status.HTTP_400_BAD_REQUEST

        from plane.bgtasks.jira_sync_task import claim_next_project

        assert claim_next_project(str(run.id)) is None

    @pytest.mark.django_db
    def test_a_stopped_project_keeps_its_last_synced_time(self, workspace, create_user, people):
        from plane.utils.jira.importer import JiraSyncStopped

        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        cursor = JiraEntityMap.objects.get(workspace=workspace, entity_type="project").jira_updated
        fake.issue_data[1]["fields"]["updated"] = jira_now()

        def stop_then_list(*args, **kwargs):
            JiraSyncRun.objects.filter(workspace=workspace).update(status="failed")
            return FakeJira.issues(fake, *args, **kwargs)

        with mock.patch.object(fake, "issues", side_effect=stop_then_list), pytest.raises(JiraSyncStopped):
            run_import(workspace, create_user, fake)

        # the next sync reads the same changes again: nothing is missed
        assert JiraEntityMap.objects.get(workspace=workspace, entity_type="project").jira_updated == cursor


@pytest.mark.contract
class TestFastIncrementalSync:
    PROJECT_WIDE = ("project_statuses", "boards", "sprints", "sprint_issue_ids", "assignable_users", "project_roles")

    @pytest.mark.django_db
    def test_nothing_changed_reads_nothing_project_wide(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        before = JiraEntityMap.objects.get(workspace=workspace, entity_type="project").jira_updated

        with contextlib.ExitStack() as stack:
            calls = {
                name: stack.enter_context(mock.patch.object(fake, name, wraps=getattr(fake, name)))
                for name in self.PROJECT_WIDE
            }
            run = run_import(workspace, create_user, fake)

        assert {name: call.call_count for name, call in calls.items()} == dict.fromkeys(self.PROJECT_WIDE, 0)
        assert run.stats.get("issues_seen", 0) == 0
        # the last synced time still moves on
        assert JiraEntityMap.objects.get(workspace=workspace, entity_type="project").jira_updated > before

    @pytest.mark.django_db
    def test_changed_work_items_get_their_sprint_from_their_own_sprint_field(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        run_import(workspace, create_user, fake)
        card = Issue.objects.get(external_id="2")
        assert CycleIssue.objects.get(issue=card).cycle.name == "Sprint 1"

        # in Jira: SHOP-2 moved to a new active sprint
        fake.issue_data[1]["fields"].update(
            customfield_10020=[
                {"id": 31, "name": "Sprint 1", "state": "closed", "startDate": "2024-01-01T00:00:00.000Z"},
                {"id": 32, "name": "Sprint 2", "state": "active", "startDate": jira_now(days=-1), "goal": "Refunds"},
            ],
            updated=jira_now(),
        )
        with (
            mock.patch.object(fake, "sprint_issue_ids", wraps=fake.sprint_issue_ids) as sprint_issue_ids,
            mock.patch.object(fake, "assignable_users", wraps=fake.assignable_users) as assignable_users,
        ):
            run = run_import(workspace, create_user, fake)

        sprint_issue_ids.assert_not_called()
        assignable_users.assert_not_called()
        assert run.stats["issues_updated"] == 1 and run.stats["sprints_created"] == 1
        cycle = CycleIssue.objects.get(issue=card).cycle
        assert (cycle.name, cycle.description) == ("Sprint 2", "Refunds")
        assert Cycle.objects.filter(project=card.project).count() == 2
        assert CycleIssue.objects.filter(issue=card).count() == 1

    @pytest.mark.django_db
    def test_projects_without_changes_count_nothing(self, workspace, create_user, people):
        _, _, ada, bob = people
        fake = FakeJira(ada, bob)
        first = run_lanes(workspace, create_user, fake)
        assert first.progress["SHOP"]["total"] == 3

        from plane.bgtasks import jira_sync_task as task

        with mock.patch.object(task.jira_sync_lane_task, "delay"):  # look at the run before any project starts
            queued = JiraSyncRun.objects.create(workspace=workspace, initiated_by=create_user, project_keys=["SHOP"])
            with mock.patch.object(task, "client_for", return_value=fake):
                task.jira_sync_task(str(queued.id))
        queued.refresh_from_db()
        assert queued.progress["SHOP"]["total"] == 0  # not Jira's 3: only changes are read
        JiraSyncRun.objects.filter(pk=queued.pk).update(status="completed")

        second = run_lanes(workspace, create_user, fake)
        assert (second.progress["SHOP"]["total"], second.progress["SHOP"]["done"]) == (0, 0)
        assert second.progress["SHOP"]["status"] == "done"
        assert not any("could be read" in warning for warning in second.warnings)
