# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Import / sync Jira projects into the workspace. Jira is only read (see JiraClient).

For every selected Jira project:
  1. the project (created once, then reused),
  2. its statuses, kept with the same names so every ticket keeps its Jira status,
  3. people (matched to workspace members by email, then by name),
  4. sprints -> sprints, components -> modules,
  5. issues: title, description, status, priority, type, assignees, reporter, labels, due date, created / updated,
  6. parent / child, links (blocks, relates, duplicates), sprint and component membership,
  7. comments, watchers, attachments and the full Jira change history of each issue.

Every Jira object is remembered in JiraEntityMap, so syncing again updates what changed and never duplicates.
Nothing here sends notifications or emails.
"""

import io
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import islice

import pytz
import requests

from crum import impersonate
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from plane.db.models import (
    Cycle,
    CustomField,
    CustomFieldValue,
    CycleIssue,
    FileAsset,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueRelation,
    IssueSequence,
    IssueSubscriber,
    JiraConnection,
    JiraEntityMap,
    JiraSyncRun,
    Label,
    Module,
    ModuleIssue,
    Profile,
    Project,
    ProjectIdentifier,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.asset_paths import asset_storage_key
from plane.utils.jira.adf import adf_to_html
from plane.utils.jira.client import JiraError
from plane.utils.work_item_types import ensure_project_work_item_types

logger = logging.getLogger("plane.worker")

SOURCE = "jira"
ADMIN, MEMBER, CLIENT = 20, 15, 5
# comments, history and watchers of the next work items are read from Jira in parallel (saving stays in order)
READ_THREADS = 4
READ_AHEAD = 16
# a re-sync reads only work items changed in Jira since the last sync of the project, plus this margin
# (clock differences between Jira and this server, edits made while the last sync was running)
SYNC_OVERLAP = timedelta(minutes=15)
CLIENT_ROLE_WORDS = re.compile(r"viewer|customer|client|observer|guest|read.?only", re.I)
TIMEZONES = set(pytz.common_timezones)
STATE_COLORS = {
    "backlog": "#A3A3A3",
    "unstarted": "#3A3A3A",
    "started": "#F59E0B",
    "completed": "#16A34A",
    "cancelled": "#9AA4BC",
}
CANCELLED_WORDS = re.compile(r"cancel|reject|won.?t|declin|abandon|invalid|duplicate|obsolete", re.I)
PRIORITIES = {
    "highest": "urgent",
    "blocker": "urgent",
    "critical": "urgent",
    "high": "high",
    "major": "high",
    "medium": "medium",
    "low": "low",
    "minor": "low",
    "lowest": "low",
    "trivial": "low",
}
# Jira history field -> activity field shown in the work item history
HISTORY_FIELDS = {
    "status": "state",
    "assignee": "assignees",
    "priority": "priority",
    "summary": "name",
    "description": "description",
    "labels": "labels",
    "sprint": "cycles",
    "duedate": "target_date",
    "issuetype": "type",
    "parent": "parent",
    "component": "modules",
    "link": "link",
    "attachment": "attachment",
    "resolution": "resolution",
    "fix version": "fix_version",
}


# how Jira names its fields in the History tab
JIRA_FIELD_LABELS = {
    "issuetype": "Issue Type",
    "status": "Status",
    "assignee": "Assignee",
    "reporter": "Reporter",
    "summary": "Summary",
    "description": "Description",
    "priority": "Priority",
    "labels": "Labels",
    "duedate": "Due date",
    "resolution": "Resolution",
    "timeestimate": "Remaining Estimate",
    "timeoriginalestimate": "Original Estimate",
    "timespent": "Time Spent",
    "worklogtimespent": "Time Spent",
    "worklogid": "Work Log",
    "epic child": "Epic Child",
    "sprint": "Sprint",
    "component": "Component",
    "fix version": "Fix versions",
    "version": "Affects versions",
    "parent": "Parent",
    "issueparentassociation": "Parent",
    "epic link": "Epic Link",
    "link": "Link",
    "attachment": "Attachment",
    "rank": "Rank",
    "environment": "Environment",
    "remoteissuelink": "Remote link",
    "project": "Project",
    "key": "Key",
}
TIME_FIELDS = {"timeestimate", "timeoriginalestimate", "timespent", "worklogtimespent"}


def format_duration(seconds):
    """Jira style duration: 1w 2d 3h 30m (a working day is 8h, a week 5 days)."""
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return str(seconds or "")
    if seconds <= 0:
        return "0m"
    parts = []
    for unit, size in (("w", 5 * 8 * 3600), ("d", 8 * 3600), ("h", 3600), ("m", 60)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
    return " ".join(parts) or "0m"


def jira_field_label(field_name):
    key = (field_name or "").lower()
    if key in JIRA_FIELD_LABELS:
        return JIRA_FIELD_LABELS[key]
    return (field_name or "Field")[:1].upper() + (field_name or "field")[1:]


# fields imported elsewhere (or internal to Jira) that do not become custom fields
SKIP_FIELDS = {
    "summary",
    "description",
    "status",
    "priority",
    "issuetype",
    "assignee",
    "reporter",
    "creator",
    "labels",
    "duedate",
    "created",
    "updated",
    "parent",
    "issuelinks",
    "attachment",
    "comment",
    "worklog",
    "watches",
    "votes",
    "subtasks",
    "project",
    "resolutiondate",
    "lastViewed",
    "statuscategorychangedate",
    "statusCategory",
    "components",
    "aggregatetimeestimate",
    "aggregatetimeoriginalestimate",
    "aggregatetimespent",
    "aggregateprogress",
    "progress",
    "workratio",
    "timetracking",
    "thumbnail",
    "issuerestriction",
    "security",
}
SKIP_SCHEMAS = {
    "com.pyxis.greenhopper.jira:gh-sprint",
    "com.pyxis.greenhopper.jira:gh-lexo-rank",
    "com.pyxis.greenhopper.jira:gh-epic-link",
    "com.pyxis.greenhopper.jira:gh-epic-status",
    "com.pyxis.greenhopper.jira:gh-epic-color",
    "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummary",
    "com.atlassian.jpo:jpo-custom-field-parent",
    "com.atlassian.servicedesk:sd-request-feedback-date",
}
TIME_TRACKING_FIELDS = {
    "timeoriginalestimate": "Original estimate",
    "timeestimate": "Time remaining",
    "timespent": "Time spent",
}
SYSTEM_FIELD_NAMES = {
    "fixVersions": "Fix versions",
    "versions": "Affects versions",
    "environment": "Environment",
    "resolution": "Resolution",
}


# Jira's own bookkeeping fields: not shown to people as fields
INTERNAL_FIELD_WORDS = ("devsummary", "charting", "issue-color", "lexo-rank", "gh-sprint", "epic-color", "epic-status")
INTERNAL_FIELD_NAMES = {"development", "issue color", "rank", "sprint", "epic color", "epic status"}


def jira_text(raw):
    """Readable text of a Jira field value (names of people, option values, rich text...)."""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return ", ".join(text for text in (jira_text(item) for item in raw) if text)
    if isinstance(raw, dict):
        if raw.get("type") == "doc":
            from bs4 import BeautifulSoup

            return BeautifulSoup(adf_to_html(raw), "html.parser").get_text("\n").strip()
        for key in ("value", "name", "displayName", "title", "key", "emailAddress"):
            if raw.get(key):
                child = raw.get("child")
                text = str(raw[key])
                return f"{text} - {jira_text(child)}" if isinstance(child, dict) and jira_text(child) else text
        return ""
    if isinstance(raw, bool):
        return "Yes" if raw else "No"
    return str(raw)


def jira_custom_value(field_id, meta, raw):
    """(field type, value) of a Jira field value, or None when it is empty."""
    if raw is None or raw == "" or raw == [] or raw == {}:
        return None
    if isinstance(raw, str) and raw.strip() in ("{}", "[]", ""):
        return None
    schema = meta.get("schema") or {}
    kind, items, custom = schema.get("type"), schema.get("items"), schema.get("custom") or ""
    if field_id in TIME_TRACKING_FIELDS:
        return "text", format_duration(raw)
    if kind == "number" and isinstance(raw, (int, float)):
        return "number", int(raw) if float(raw).is_integer() else raw
    if kind == "date" and isinstance(raw, str):
        return "date", raw[:10]
    if kind == "datetime" and isinstance(raw, str):
        moment = jira_datetime(raw)
        return "text", moment.strftime("%d %b %Y %H:%M") if moment else raw
    if isinstance(raw, bool):
        return "checkbox", raw
    if kind == "string" and isinstance(raw, dict) and raw.get("type") == "doc":
        text = jira_text(raw)
        return ("textarea", text) if text else None
    if kind == "string":
        text = str(raw)
        return ("textarea" if "textarea" in custom or len(text) > 255 else "text"), text
    if kind in ("option", "option-with-child", "resolution", "priority", "version", "component"):
        text = jira_text(raw)
        return ("select", text) if text else None
    if kind == "array" and items in ("option", "string", "version", "component") and isinstance(raw, list):
        values = [text for text in (jira_text(item) for item in raw) if text]
        return ("multi_select", list(dict.fromkeys(values))) if values else None
    text = jira_text(raw)
    return ("text", text[:2000]) if text else None


def coerce_value(field_type, kind, value):
    """Fit a value to an existing field whose type was decided by an earlier work item."""
    if field_type == kind:
        return value
    if field_type == "multi_select":
        return value if isinstance(value, list) else [str(value)]
    if field_type == "select":
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    if field_type in ("text", "textarea"):
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    if field_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def jira_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return None
    return parsed


def state_group(status):
    category = ((status.get("statusCategory") or {}).get("key") or "").lower()
    name = status.get("name") or ""
    if category == "done":
        return "cancelled" if CANCELLED_WORDS.search(name) else "completed"
    if category == "indeterminate":
        return "started"
    if "backlog" in name.lower():
        return "backlog"
    return "unstarted"


def type_key(issue_type):
    name = ((issue_type or {}).get("name") or "").lower()
    if name == "epic" or (issue_type or {}).get("hierarchyLevel") == 1:
        return "feature"
    if "bug" in name or "defect" in name:
        return "bug"
    return "task"


class JiraSyncStopped(Exception):
    """The run was stopped (Stop sync): the project being synced ends at the next progress save."""


def last_synced_at(workspace, project_key, mapping=None, runs=None):
    """When the project's last sync started that finished (changes in Jira after it are read again); None: never.

    Kept on the project's JiraEntityMap; projects synced before that was kept fall back to their sync runs.
    """
    moment = parse_datetime(mapping.jira_updated) if mapping is not None and mapping.jira_updated else None
    if moment is not None:
        return moment
    if runs is None:
        runs = (
            JiraSyncRun.objects.filter(
                workspace=workspace, project_keys__contains=[project_key], status__in=("completed", "failed")
            )
            .exclude(started_at__isnull=True)
            .order_by("-started_at")
        )
    for run in runs:
        if project_key not in (run.project_keys or []) or run.started_at is None:
            continue
        state = (run.progress or {}).get(project_key)
        if state is None:
            # runs from before projects had their own progress: only a completed run says the project finished
            if run.status == "completed" and not run.progress:
                return run.started_at
            continue
        if state.get("status") == "done":
            return parse_datetime(state.get("started_at") or "") or run.started_at
    return None


class JiraImporter:
    def __init__(self, run, client, workspace, actor, directory=None):
        self.run = run
        # accountId -> {email, name, active, org_admin, ...} from the organization directory (see sync_users)
        self.directory = directory or {}
        self.client = client
        self.workspace = workspace
        self.actor = actor
        self.options = {"attachments": True, "history": True, "comments": True, "full": False, **(run.options or {})}
        # what this importer adds; merged into the run (other workers may sync other projects at the same time)
        self.stats = {}
        self.new_warnings = []
        self.new_projects = {}
        self.resolved = set()
        self.project_key = None
        # set while a project is re-synced: only work items changed in Jira after this moment are read
        self.since = None
        self.items_done = 0
        self.user_cache = {}
        self.unmatched = {entry.get("account_id"): entry for entry in run.unmatched_users or []}
        self.jira_fields = None
        self.group_cache = {}
        self.member_cache = set()
        self.read_local = threading.local()
        self.last_saved = 0.0
        self.members = list(
            WorkspaceMember.objects.filter(workspace=workspace, is_active=True, member__is_bot=False).select_related(
                "member"
            )
        )

    # ---- helpers --------------------------------------------------------------------------------------------------
    def count(self, key, amount=1):
        self.stats[key] = self.stats.get(key, 0) + amount

    def warn(self, message):
        self.new_warnings.append(message)

    def save_progress(self, step=None):
        """Merge what this importer did into the run, under a row lock (workers run in parallel)."""
        with transaction.atomic():
            run = JiraSyncRun.objects.select_for_update().get(pk=self.run.pk)
            stopped = run.status == "failed"
            for key, amount in self.stats.items():
                run.stats[key] = run.stats.get(key, 0) + amount
            room = max(0, 200 - len(run.warnings))
            run.warnings.extend(self.new_warnings[:room])
            if len(self.new_warnings) > room:
                run.stats["more_warnings"] = run.stats.get("more_warnings", 0) + len(self.new_warnings) - room
            run.projects.update(self.new_projects)
            unmatched = {entry.get("account_id"): entry for entry in run.unmatched_users or []}
            unmatched.update(self.unmatched)
            for account_id in self.resolved:
                unmatched.pop(account_id, None)
            run.unmatched_users = list(unmatched.values())
            if step:
                run.current_step = step[:255]
            if self.project_key and self.project_key in run.progress:
                state = run.progress[self.project_key]
                state.update(done=self.items_done, step=(step or state.get("step", ""))[:255])
                if self.since is not None:
                    # Jira's count is of every work item; a re-sync reads only the changed ones
                    state.update(total=self.items_done, since=self.since.isoformat())
                else:
                    state["total"] = max(state.get("total") or 0, self.items_done)
                state["heartbeat"] = timezone.now().isoformat()
            run.save(
                update_fields=[
                    "current_step",
                    "stats",
                    "warnings",
                    "unmatched_users",
                    "projects",
                    "progress",
                    "updated_at",
                ]
            )
        self.run = run
        self.last_saved = time.monotonic()
        self.stats, self.new_warnings, self.new_projects = {}, [], {}
        if stopped:
            # what was saved so far stays; the project's "last synced" time does not move, so nothing is missed
            raise JiraSyncStopped("Stopped")

    def get_map(self, entity_type, jira_id):
        return JiraEntityMap.objects.filter(
            workspace=self.workspace, entity_type=entity_type, jira_id=str(jira_id)
        ).first()

    def set_map(self, entity_type, jira_id, plane_id, jira_key="", jira_updated=""):
        record, _ = JiraEntityMap.objects.update_or_create(
            workspace=self.workspace,
            entity_type=entity_type,
            jira_id=str(jira_id),
            defaults={"plane_id": plane_id, "jira_key": jira_key or "", "jira_updated": jira_updated or ""},
        )
        return record

    # ---- people -----------------------------------------------------------------------------------------------
    def user_for(self, jira_user, project=None):
        """Workspace member for a Jira user (email first, then display name); None when not found."""
        if not jira_user:
            return None
        account_id = jira_user.get("accountId") or jira_user.get("name") or jira_user.get("displayName")
        if account_id in self.user_cache:
            user = self.user_cache[account_id]
        else:
            email = (jira_user.get("emailAddress") or "").strip().lower()
            name = (jira_user.get("displayName") or "").strip().lower()
            mapped = self.get_map("user", account_id) if jira_user.get("accountId") else None
            user = next((m.member for m in self.members if mapped and str(m.member_id) == str(mapped.plane_id)), None)
            if user is None and email:
                user = next((m.member for m in self.members if (m.member.email or "").lower() == email), None)
            if user is None and name:
                user = next(
                    (
                        m.member
                        for m in self.members
                        if name
                        in {
                            (m.member.display_name or "").lower(),
                            f"{m.member.first_name or ''} {m.member.last_name or ''}".strip().lower(),
                        }
                    ),
                    None,
                )
            if user is None and project is not None and self.is_former_person(jira_user):
                user = self.former_account(jira_user)
            self.user_cache[account_id] = user
            if user is None and account_id not in self.unmatched and jira_user.get("accountType") != "app":
                self.unmatched[account_id] = {
                    "account_id": account_id,
                    "name": jira_user.get("displayName") or "",
                    "email": jira_user.get("emailAddress") or "",
                }
        if user is not None and project is not None:
            self.ensure_member(project, user)
        return user

    def ensure_member(self, project, user, role=MEMBER):
        # checked once per person and project (history alone asks for the same people thousands of times)
        if (project.id, user.id) in self.member_cache:
            return
        self.member_cache.add((project.id, user.id))
        membership = ProjectMember.objects.filter(project=project, member=user).first()
        if membership is None:
            workspace_role = next((m.role for m in self.members if m.member_id == user.id), MEMBER)
            ProjectMember.objects.create(
                project=project,
                workspace=self.workspace,
                member=user,
                role=ADMIN if workspace_role == ADMIN else min(role, workspace_role),
                designation="Team member",
            )
        elif not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active", "updated_at"])

    @staticmethod
    def project_role(role_name):
        """Project role and designation for a Jira project role (Administrators, Developers, Viewers, ...)."""
        name = (role_name or "").strip()
        # read only wins over admin ("Read Only Admin" can only look)
        if CLIENT_ROLE_WORDS.search(name):
            role = CLIENT
        elif "admin" in name.lower():
            role = ADMIN
        else:
            role = MEMBER
        designation = name[:-1] if len(name) > 3 and name.endswith("s") and not name.endswith("ss") else name
        return role, designation or "Team member"

    def sync_project_people(self, project, project_key):
        """Like in Jira: everyone who can be assigned work in the Jira project is a member, with their role."""
        try:
            assignable = self.client.assignable_users(project_key)
        except JiraError as error:
            self.warn(f"{project_key}: assignable people not read ({error})")
            assignable = []
        unmatched = dict(self.unmatched)
        for person in assignable:
            if person.get("accountType", "atlassian") == "atlassian" and person.get("active", True):
                self.user_for(person, project)
        # being assignable is not work: only people on work items are listed as missing
        self.unmatched = unmatched
        self.sync_project_roles(project, project_key)

    def relink_people(self, project, project_key):
        """After a user sync: work items, comments and history imported before people had accounts get them."""
        self.save_progress(f"{project_key}: assigning work items to people")
        for jira_issue in self.client.issues(project_key, fields="assignee,reporter,creator"):
            mapping = self.get_map("issue", jira_issue["id"])
            issue = Issue.objects.filter(pk=mapping.plane_id, project=project).first() if mapping else None
            if issue is None:
                continue
            fields = jira_issue.get("fields") or {}
            assignee = self.user_for(fields.get("assignee"), project)
            if assignee and not IssueAssignee.objects.filter(issue=issue, assignee=assignee).exists():
                IssueAssignee.objects.filter(issue=issue).delete()
                IssueAssignee.objects.create(issue=issue, assignee=assignee, project=project, workspace=self.workspace)
                IssueSubscriber.objects.get_or_create(
                    issue=issue, subscriber=assignee, defaults={"project": project, "workspace": self.workspace}
                )
                self.count("assignees_linked")
            reporter = self.user_for(fields.get("reporter") or fields.get("creator"), project)
            if reporter and issue.created_by_id != reporter.id:
                Issue.all_objects.filter(pk=issue.pk).update(created_by_id=reporter.id)
                IssueActivity.objects.filter(issue=issue, verb="created", field__isnull=True).update(actor=reporter)
                self.count("reporters_linked")
        # history entries and comments recorded with only the Jira name
        names = {}
        for member in self.members:
            name = (member.member.display_name or "").strip()
            if name:
                names.setdefault(name, set()).add(member.member)
        for name, users in names.items():
            if len(users) != 1:
                continue  # two people with one name: leave the name
            (user,) = users
            linked = IssueActivity.objects.filter(
                project=project, external_source=SOURCE, external_actor_name=name, actor__isnull=True
            ).update(actor=user)
            prefix = f"<p><em>{name} (Jira)</em></p>"
            for comment in IssueComment.objects.filter(
                project=project, external_source=SOURCE, comment_html__startswith=prefix
            ):
                comment.comment_html = comment.comment_html[len(prefix) :]
                comment.actor = user
                comment.save(update_fields=["comment_html", "actor", "updated_at"])
                linked += 1
            if linked:
                self.count("history_linked", linked)

    def sync_project_roles(self, project, project_key):
        """Members of the Jira project's roles join the project with the same role (highest one wins)."""
        try:
            roles = self.client.project_roles(project_key)
        except JiraError as error:
            self.warn(f"{project_key}: project roles not read ({error})")
            return
        wanted = {}
        for jira_role in roles:
            if (jira_role.get("name") or "").lower().startswith("atlassian-addons"):
                continue  # the role Jira apps use
            role, designation = self.project_role(jira_role.get("name"))
            for actor in jira_role.get("actors") or []:
                if actor.get("actorUser"):
                    people = [
                        {"accountId": actor["actorUser"].get("accountId"), "displayName": actor.get("displayName")}
                    ]
                elif actor.get("actorGroup", {}).get("groupId"):
                    people = self.group_people(actor["actorGroup"]["groupId"])
                else:
                    continue
                for person in people:
                    if person.get("accountType", "atlassian") != "atlassian" or person.get("active") is False:
                        continue
                    user = self.user_for(person)
                    if user is not None and (user.id not in wanted or wanted[user.id][0] < role):
                        wanted[user.id] = (role, designation)
        for user_id, (role, designation) in wanted.items():
            workspace_role = next((m.role for m in self.members if m.member_id == user_id), None)
            if workspace_role is None:
                continue
            if workspace_role == CLIENT:
                role = CLIENT
            key = f"{project.id}:{user_id}"
            synced = f"{role}:{designation}"
            membership = ProjectMember.objects.filter(project=project, member_id=user_id).first()
            if membership is None:
                ProjectMember.objects.create(
                    project=project, workspace=self.workspace, member_id=user_id, role=role, designation=designation
                )
                self.count("project_members_added")
            else:
                # follow Jira only while the membership is as the sync left it; changes made here are kept
                last = self.get_map("project_member", key)
                current = f"{membership.role}:{membership.designation}"
                untouched = (last and last.jira_key == current) or membership.designation in ("", "Team member")
                if not untouched:
                    continue
                if current != synced or not membership.is_active:
                    membership.role, membership.designation, membership.is_active = role, designation, True
                    membership.save(update_fields=["role", "designation", "is_active", "updated_at"])
                    self.count("project_roles_updated")
            self.set_map("project_member", key, str(user_id), jira_key=synced)

    @staticmethod
    def avatar_source(jira_user):
        """The person's own photo in Jira, or "" when Jira only has the generated initials picture."""
        url = (jira_user.get("avatarUrls") or {}).get("48x48") or ""
        # no photo: a gravatar link falling back to Atlassian's initials image (initials are drawn here instead)
        if not url or ("gravatar.com" in url and "initials" in url) or "/initials/" in url:
            return ""
        return url

    def fetch_avatar(self, url):
        """Download a public avatar image (GET only; it is not Jira data)."""
        response = requests.get(url, timeout=15)
        mime = (response.headers.get("Content-Type") or "").split(";")[0]
        if response.status_code != 200 or not mime.startswith("image/") or len(response.content) > 2 * 1024 * 1024:
            return None, None
        return response.content, mime

    def set_avatar(self, user, jira_user):
        """Keep the person's Jira photo in this app's own storage (fast, no calls to outside sites when shown)."""
        from plane.settings.storage import S3Storage

        source = self.avatar_source(jira_user)
        current = user.avatar_asset
        if current is not None and (current.attributes or {}).get("source") == source and source:
            return
        if not source:
            if user.avatar or (current is not None and (current.attributes or {}).get("source")):
                user.avatar, user.avatar_asset = "", None
                user.save(update_fields=["avatar", "avatar_asset", "updated_at"])
            return
        try:
            content, mime = self.fetch_avatar(source)
        except Exception as error:  # a missing photo never stops the sync: initials are shown instead
            logger.warning("Jira avatar not downloaded: %s", error)
            content = None
        if not content:
            return
        name = f"avatar.{mime.split('/')[-1].split('+')[0]}"
        key = asset_storage_key(name, entity_type=FileAsset.EntityTypeContext.USER_AVATAR, user_id=user.id)
        if not S3Storage(request=None).upload_file(io.BytesIO(content), key, mime):
            return
        asset = FileAsset.objects.create(
            attributes={"name": name, "type": mime, "size": len(content), "source": source},
            asset=key,
            size=len(content),
            user=user,
            entity_type=FileAsset.EntityTypeContext.USER_AVATAR,
            is_uploaded=True,
        )
        user.avatar, user.avatar_asset = "", asset
        user.save(update_fields=["avatar", "avatar_asset", "updated_at"])
        self.count("avatars_stored")

    @staticmethod
    def is_former_person(jira_user):
        """A person on imported work without an account here (deactivated, removed from the site, or not synced)."""
        return jira_user.get("accountType", "atlassian") == "atlassian" and bool(jira_user.get("accountId"))

    def former_account(self, jira_user, user=None):
        """A disabled account (no email, no login) for a person on imported work who has no account here.

        It keeps their Jira name and avatar so they show as assignee / reporter like in Jira, and it is a member so
        the work items can show them; it can never sign in and is never emailed. A later user sync that finds the
        person active with an email turns it into a normal account.
        """
        account_id = jira_user["accountId"]
        name = (jira_user.get("displayName") or "Former Jira user").strip()
        if user is None:
            user = User(
                email=None,
                username=uuid.uuid4().hex,
                display_name=name,
                first_name=name.partition(" ")[0][:255],
                last_name=name.partition(" ")[2][:255],
                is_password_autoset=True,
            )
            user.set_unusable_password()
            self.count("former_accounts_created")
        user.is_active = False
        user.save()
        self.set_avatar(user, jira_user)
        membership = WorkspaceMember.objects.filter(workspace=self.workspace, member=user).first()
        if membership is None:
            membership = WorkspaceMember.objects.create(workspace=self.workspace, member=user, role=MEMBER)
        elif not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active", "updated_at"])
        self.members.append(membership)
        self.set_map("user", account_id, str(user.id), jira_key=user.email or "", jira_updated="former")
        self.unmatched.pop(account_id, None)
        self.resolved.add(account_id)
        return user

    def deactivate_user(self, mapped, person):
        """A person deactivated in Jira (or the organization) can no longer work here; history keeps their name.

        Accounts this sync made become former accounts (no login, still shown on their work items); accounts
        people made themselves just leave the workspace.
        """
        if mapped is None or str(mapped.plane_id) == str(self.actor.id) or mapped.jira_updated in ("former", "invited"):
            # "invited": an admin gave the person an email and invited them here; that stays their call
            return
        if mapped.jira_updated == "created":
            user = User.objects.filter(pk=mapped.plane_id).first()
            if user is not None:
                self.former_account(person, user)
                self.count("users_deactivated")
            return
        changed = WorkspaceMember.objects.filter(
            workspace=self.workspace, member_id=mapped.plane_id, is_active=True
        ).update(is_active=False)
        ProjectMember.objects.filter(workspace=self.workspace, member_id=mapped.plane_id, is_active=True).update(
            is_active=False
        )
        if changed:
            self.count("users_deactivated")

    def group_people(self, group_id):
        if group_id not in self.group_cache:
            try:
                self.group_cache[group_id] = self.client.group_members(group_id)
            except JiraError as error:
                self.warn(f"Jira group {group_id} not read ({error})")
                self.group_cache[group_id] = []
        return self.group_cache[group_id]

    def jira_admin_ids(self):
        """Account ids of Jira site/product admins (members of groups named like *admin*)."""
        ids = set()
        try:
            groups = self.client.groups()
        except JiraError as error:
            self.warn(f"Jira groups not read, everyone joins as Member ({error})")
            return ids
        for group in groups:
            if "admin" in (group.get("name") or "").lower() and group.get("groupId"):
                ids.update(person.get("accountId") for person in self.group_people(group["groupId"]))
        return ids

    def sync_users(self):
        """Every active Jira person gets an account (same name, email, avatar, time zone) in this workspace.

        Jira hides most emails from API tokens, so emails (and the organization's own user status and admin role)
        come from the organization directory when one is given: the admin API or the exported users file.
        """
        self.save_progress("Reading Jira users")
        people = [
            person
            for person in self.client.users()
            if person.get("accountType") == "atlassian" and person.get("accountId")
        ]
        admins = self.jira_admin_ids()
        without_email = []
        self.save_progress(f"Adding {len(people)} users")
        for person in people:
            account_id = person["accountId"]
            listed = (
                self.directory.get(account_id)
                or self.directory.get(f"name:{(person.get('displayName') or '').strip().lower()}")
                or {}
            )
            mapped = self.get_map("user", account_id)
            if not person.get("active") or (listed and not listed["active"]):
                self.deactivate_user(mapped, person)
                continue
            # the email Jira shows, else the directory's, else the one an earlier user sync was given
            email = (
                (person.get("emailAddress") or listed.get("email") or (mapped.jira_key if mapped else "") or "")
                .strip()
                .lower()
            )
            name = (person.get("displayName") or listed.get("name") or "").strip()
            if not email:
                without_email.append(name or account_id)
                self.unmatched[account_id] = {"account_id": account_id, "name": name, "email": "", "reason": "no_email"}
                continue
            role = ADMIN if account_id in admins or listed.get("org_admin") else MEMBER
            time_zone = person.get("timeZone") or listed.get("time_zone")
            details = {
                "display_name": name or email.split("@")[0],
                "first_name": name.partition(" ")[0][:255],
                "last_name": name.partition(" ")[2][:255],
                "user_timezone": time_zone if time_zone in TIMEZONES else "UTC",
            }
            user = User.objects.filter(email__iexact=email).first()
            if user is None and mapped is not None and mapped.jira_updated == "former":
                # back in Jira: the former account becomes a normal one
                user = User.objects.filter(pk=mapped.plane_id).first()
                if user is not None:
                    user.email, user.is_active, user.is_email_verified = email, True, True
                    user.set_password(uuid.uuid4().hex)
                    user.save()
                    mapped.jira_updated = "created"
            # accounts this sync made follow Jira (name, avatar, role); accounts people made themselves are kept
            made_here = user is None or (mapped is not None and mapped.jira_updated == "created")
            if user is None:
                user = User(email=email, username=uuid.uuid4().hex, is_password_autoset=True, is_email_verified=True)
                user.set_password(uuid.uuid4().hex)
                for key, value in details.items():
                    setattr(user, key, value)
                user.save()
                self.count("users_created")
            elif made_here and any(getattr(user, key) != value for key, value in details.items()):
                for key, value in details.items():
                    setattr(user, key, value)
                user.save(update_fields=[*details, "updated_at"])
                self.count("users_updated")
            # also accounts holding a link to Jira's picture (made by an earlier version of this sync)
            if made_here or self.avatar_source({"avatarUrls": {"48x48": user.avatar}}) != user.avatar:
                self.set_avatar(user, person)
            Profile.objects.get_or_create(
                user=user,
                defaults={
                    "is_onboarded": True,
                    "last_workspace_id": self.workspace.id,
                    "onboarding_step": {
                        "profile_complete": True,
                        "workspace_create": True,
                        "workspace_invite": True,
                        "workspace_join": True,
                    },
                },
            )
            membership = WorkspaceMember.objects.filter(workspace=self.workspace, member=user).first()
            if membership is None:
                WorkspaceMember.objects.create(workspace=self.workspace, member=user, role=role)
                self.count("users_added")
            else:
                # Jira admins are raised to Admin; only accounts this sync made are also lowered
                new_role = role if made_here and user.id != self.actor.id else max(membership.role, role)
                if not membership.is_active or membership.role != new_role:
                    self.count("users_role_updated" if membership.is_active else "users_added")
                    membership.is_active, membership.role = True, new_role
                    membership.save(update_fields=["is_active", "role", "updated_at"])
                else:
                    self.count("users_existing")
            self.set_map("user", account_id, str(user.id), jira_key=email, jira_updated="created" if made_here else "")
            self.unmatched.pop(account_id, None)
            self.resolved.add(account_id)
        # former people (no longer on the Jira site) imported with a link to an outside picture: initials instead
        former_ids = JiraEntityMap.objects.filter(
            workspace=self.workspace, entity_type="user", jira_updated="former"
        ).values_list("plane_id", flat=True)
        User.objects.filter(pk__in=list(former_ids), avatar__startswith="http").update(avatar="")
        if without_email:
            self.count("users_without_email", len(without_email))
            self.warn(
                f"{len(without_email)} people: Jira does not share their email, so no account was made. Add the "
                "Atlassian organization admin API key or upload the users file exported from admin.atlassian.com "
                "and sync users again."
            )
        self.members = list(
            WorkspaceMember.objects.filter(
                workspace=self.workspace, is_active=True, member__is_bot=False
            ).select_related("member")
        )
        self.user_cache = {}
        # projects imported before get the Jira project roles of the people just added
        for mapped in JiraEntityMap.objects.filter(workspace=self.workspace, entity_type="project"):
            project = Project.objects.filter(pk=mapped.plane_id, workspace=self.workspace).first()
            if project is not None:
                key = mapped.jira_key or mapped.jira_id
                self.save_progress(f"{key}: project members")
                try:
                    self.sync_project_people(project, key)
                    self.relink_people(project, key)
                except JiraError as error:
                    self.warn(f"{key}: {error}")
        self.save_progress("Finished")

    # ---- project ----------------------------------------------------------------------------------------------
    def unique_identifier(self, key):
        base = re.sub(r"[^A-Z0-9]", "", (key or "JIRA").upper())[:12] or "JIRA"
        candidate, number = base, 1
        while Project.objects.filter(workspace=self.workspace, identifier=candidate).exists() or (
            ProjectIdentifier.objects.filter(workspace=self.workspace, name=candidate).exists()
        ):
            suffix = str(number)
            candidate = f"{base[: 12 - len(suffix)]}{suffix}"
            number += 1
        return candidate

    def unique_name(self, name):
        base = re.sub(r"[&+,:;$^}{*=?@#|'<>.()%!-]", " ", name or "Jira project").strip()[:240] or "Jira project"
        candidate, number = base, 2
        while Project.objects.filter(workspace=self.workspace, name=candidate).exists():
            candidate = f"{base} ({number})"
            number += 1
        return candidate

    def project_for(self, jira_project):
        """(project, when it last finished syncing or None for a new project)."""
        mapping = self.get_map("project", jira_project["id"])
        project = Project.objects.filter(pk=mapping.plane_id, workspace=self.workspace).first() if mapping else None
        synced_at = None
        if project is None:
            identifier = self.unique_identifier(jira_project.get("key"))
            with transaction.atomic():
                project = Project.objects.create(
                    workspace=self.workspace,
                    name=self.unique_name(jira_project.get("name")),
                    identifier=identifier,
                    description=(jira_project.get("description") or "")[:5000],
                    network=2,
                    created_by=self.actor,
                    updated_by=self.actor,
                )
                ProjectIdentifier.objects.create(name=identifier, project=project, workspace=self.workspace)
                ProjectMember.objects.create(
                    project=project,
                    workspace=self.workspace,
                    member=self.actor,
                    role=ADMIN,
                    designation="Project Admin",
                )
            ensure_project_work_item_types(project)
            self.count("projects_created")
        else:
            self.count("projects_updated")
            synced_at = last_synced_at(self.workspace, jira_project.get("key"), mapping)
        self.set_map(
            "project",
            jira_project["id"],
            project.id,
            jira_project.get("key"),
            jira_updated=synced_at.isoformat() if synced_at else "",
        )
        lead = self.user_for(jira_project.get("lead"), project)
        if lead and project.project_lead_id != lead.id:
            project.project_lead = lead
            project.save(update_fields=["project_lead", "updated_at"])
        return project, synced_at

    # ---- statuses -----------------------------------------------------------------------------------------------
    def states_for(self, project, project_key):
        states = {}
        existing = {state.name.lower(): state for state in State.objects.filter(project=project)}
        sequence = max([state.sequence for state in existing.values()], default=0)
        for status in self.client.project_statuses(project_key):
            mapping = self.get_map("status", f"{project.id}:{status['id']}")
            state = State.objects.filter(pk=mapping.plane_id).first() if mapping else None
            if state is None:
                state = existing.get(status["name"].lower())
            if state is None:
                group = state_group(status)
                sequence += 15000
                state = State.objects.create(
                    project=project,
                    workspace=self.workspace,
                    name=status["name"][:255],
                    group=group,
                    color=STATE_COLORS[group],
                    sequence=sequence,
                    created_by=self.actor,
                )
                existing[state.name.lower()] = state
                self.count("statuses_created")
            self.set_map("status", f"{project.id}:{status['id']}", state.id, status["name"])
            states[str(status["id"])] = state
        # work items need a default state (the first "not started" one)
        if not State.objects.filter(project=project, default=True).exists() and states:
            default = next(
                (s for s in states.values() if s.group in ("unstarted", "backlog")), next(iter(states.values()))
            )
            State.objects.filter(pk=default.pk).update(default=True)
        return states

    # ---- sprints and components ------------------------------------------------------------------------------------
    def sprints_for(self, project, project_key):
        """Sprints -> cycles. Returns {jira issue id: cycle} using the issue's latest sprint."""
        issue_cycle = {}
        try:
            boards = self.client.boards(project_key)
        except JiraError as error:
            self.warn(f"{project_key}: sprints not imported ({error}).")
            return issue_cycle
        seen = set()
        for board in boards:
            try:
                sprints = self.client.sprints(board["id"])
            except JiraError:
                continue  # kanban boards have no sprints
            for sprint in sprints:
                if sprint["id"] in seen:
                    continue
                seen.add(sprint["id"])
                cycle = self.sprint_cycle(project, sprint)
                try:
                    issue_ids = self.client.sprint_issue_ids(sprint["id"])
                except JiraError:
                    issue_ids = []
                for issue_id in issue_ids:
                    current = issue_cycle.get(str(issue_id))
                    order = self.sprint_order(sprint)
                    if current is None or order > current[0]:
                        issue_cycle[str(issue_id)] = (order, cycle)
        return {issue_id: value[1] for issue_id, value in issue_cycle.items()}

    @staticmethod
    def sprint_order(sprint):
        """A work item in several sprints belongs to the active one, else the future one, else the latest closed."""
        rank = {"closed": 0, "future": 1, "active": 2}
        return (rank.get(sprint.get("state"), 0), jira_datetime(sprint.get("startDate")) or timezone.now())

    def sprint_cycle(self, project, sprint):
        """The cycle of a Jira sprint, created or updated (name, goal, dates)."""
        mapping = self.get_map("sprint", sprint["id"])
        cycle = Cycle.objects.filter(pk=mapping.plane_id).first() if mapping else None
        values = {
            "name": (sprint.get("name") or f"Sprint {sprint['id']}")[:255],
            "description": sprint.get("goal") or "",
            "start_date": jira_datetime(sprint.get("startDate")),
            "end_date": jira_datetime(sprint.get("completeDate") or sprint.get("endDate")),
        }
        if cycle is None:
            cycle = Cycle.objects.create(
                project=project,
                workspace=self.workspace,
                owned_by=self.actor,
                created_by=self.actor,
                external_source=SOURCE,
                external_id=str(sprint["id"]),
                **values,
            )
            self.count("sprints_created")
        else:
            Cycle.objects.filter(pk=cycle.pk).update(**values)
        self.set_map("sprint", sprint["id"], cycle.id, sprint.get("name") or "")
        return cycle

    def sprints_of_issues(self, project, jira_issues):
        """{jira issue id: cycle} from the work items' own Sprint field: a re-sync reads only the changed work items,
        not every sprint of every board."""
        sprint_fields = [
            field_id
            for field_id, meta in self.field_meta().items()
            if ((meta.get("schema") or {}).get("custom") or "") == "com.pyxis.greenhopper.jira:gh-sprint"
        ]
        issue_cycle, cycles = {}, {}
        for jira_issue in jira_issues:
            fields = jira_issue.get("fields") or {}
            sprints = [
                sprint
                for field_id in sprint_fields
                for sprint in fields.get(field_id) or []
                if isinstance(sprint, dict) and sprint.get("id") is not None
            ]
            if not sprints:
                continue
            sprint = max(sprints, key=self.sprint_order)
            if sprint["id"] not in cycles:
                cycles[sprint["id"]] = self.sprint_cycle(project, sprint)
            issue_cycle[str(jira_issue["id"])] = cycles[sprint["id"]]
        return issue_cycle

    def modules_for(self, project, jira_project):
        modules = {}
        for component in jira_project.get("components") or []:
            mapping = self.get_map("component", component["id"])
            module = Module.objects.filter(pk=mapping.plane_id).first() if mapping else None
            if module is None:
                module = Module.objects.filter(project=project, name=component["name"][:255]).first()
            if module is None:
                module = Module.objects.create(
                    project=project,
                    workspace=self.workspace,
                    name=component["name"][:255],
                    description=component.get("description") or "",
                    created_by=self.actor,
                )
                self.count("modules_created")
            self.set_map("component", component["id"], module.id, component["name"])
            modules[str(component["id"])] = module
        return modules

    # ---- issues -----------------------------------------------------------------------------------------------
    def label_for(self, project, name):
        label = Label.objects.filter(project=project, name=name[:255]).first()
        if label is None:
            label = Label.objects.create(
                project=project, workspace=self.workspace, name=name[:255], color="#6B7280", created_by=self.actor
            )
        return label

    def upsert_issue(self, project, jira_issue, states, types):
        fields = jira_issue.get("fields") or {}
        mapping = self.get_map("issue", jira_issue["id"])
        issue = Issue.all_objects.filter(pk=mapping.plane_id, project=project).first() if mapping else None
        if issue is not None and issue.deleted_at is not None:
            # deleted here on purpose: leave it deleted
            return None, False
        unchanged = (
            issue is not None
            and not self.options["full"]
            and mapping.jira_updated
            and mapping.jira_updated == (fields.get("updated") or "")
        )
        if unchanged:
            self.count("issues_unchanged")
            return issue, False

        attachments = {str(a.get("id")): a.get("filename") for a in fields.get("attachment") or []}
        reporter = self.user_for(fields.get("reporter") or fields.get("creator"), project)
        state = states.get(str((fields.get("status") or {}).get("id")))
        priority = PRIORITIES.get(((fields.get("priority") or {}).get("name") or "").lower(), "none")
        values = {
            "name": (fields.get("summary") or jira_issue.get("key") or "Untitled")[:255],
            "description_html": adf_to_html(fields.get("description"), attachments),
            "priority": priority,
            "target_date": fields.get("duedate") or None,
            "type": types.get(type_key(fields.get("issuetype"))),
            "external_source": SOURCE,
            "external_id": str(jira_issue["id"]),
        }
        if state is not None:
            values["state"] = state
        if issue is None:
            issue = Issue(project=project, workspace=self.workspace, created_by=reporter or self.actor, **values)
            issue.save()
            self.count("issues_created")
            created = True
        else:
            for key, value in values.items():
                setattr(issue, key, value)
            issue.updated_by = self.actor
            issue.save()
            self.count("issues_updated")
            created = False

        # keep Jira's own dates and reporter (save() would take them from the current request)
        timestamps = {"created_by_id": (reporter or self.actor).id} if created else {}
        if jira_datetime(fields.get("created")):
            timestamps["created_at"] = jira_datetime(fields.get("created"))
        if jira_datetime(fields.get("updated")):
            timestamps["updated_at"] = jira_datetime(fields.get("updated"))
        if state is not None and state.group == "completed" and jira_datetime(fields.get("resolutiondate")):
            timestamps["completed_at"] = jira_datetime(fields.get("resolutiondate"))
        if timestamps:
            Issue.all_objects.filter(pk=issue.pk).update(**timestamps)

        # assignee (Jira has one) and labels: Jira is the source of truth for imported work items
        assignee = self.user_for(fields.get("assignee"), project)
        IssueAssignee.objects.filter(issue=issue).exclude(assignee=assignee).delete()
        if assignee and not IssueAssignee.objects.filter(issue=issue, assignee=assignee).exists():
            IssueAssignee.objects.create(issue=issue, assignee=assignee, project=project, workspace=self.workspace)
        label_ids = [self.label_for(project, name).id for name in fields.get("labels") or []]
        IssueLabel.objects.filter(issue=issue).exclude(label_id__in=label_ids).delete()
        for label_id in label_ids:
            if not IssueLabel.objects.filter(issue=issue, label_id=label_id).exists():
                IssueLabel.objects.create(issue=issue, label_id=label_id, project=project, workspace=self.workspace)

        # Jira people watching the issue (and its reporter / assignee) watch it here too
        for user in {reporter, assignee} - {None}:
            IssueSubscriber.objects.get_or_create(
                issue=issue, subscriber=user, defaults={"project": project, "workspace": self.workspace}
            )
        # Jira's "updated" is recorded once comments, history and attachments are saved too (see sync_issue): a
        # sync stopped half way reads the work item again next time instead of taking it as unchanged
        self.set_map(
            "issue", jira_issue["id"], issue.id, jira_issue.get("key"), mapping.jira_updated if mapping else ""
        )
        self.sync_custom_fields(project, issue, fields)
        if created:
            self.log_created(issue, jira_issue, reporter)
        else:
            # entries imported before the Jira names were kept
            IssueActivity.objects.filter(
                issue=issue,
                verb="created",
                field__isnull=True,
                external_source__isnull=True,
                comment__startswith="imported the work item from Jira",
            ).update(external_source=SOURCE, external_actor_name=self.person_name(fields.get("reporter")))
        return issue, True

    def log_created(self, issue, jira_issue, reporter):
        activity = IssueActivity.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace=self.workspace,
            actor=reporter,
            verb="created",
            comment=f"imported the work item from Jira ({jira_issue.get('key')})",
            epoch=int(timezone.now().timestamp()),
            external_source=SOURCE,
            external_actor_name=self.person_name(
                (jira_issue.get("fields") or {}).get("reporter") or (jira_issue.get("fields") or {}).get("creator")
            ),
        )
        created_at = jira_datetime((jira_issue.get("fields") or {}).get("created"))
        if created_at:
            IssueActivity.objects.filter(pk=activity.pk).update(created_at=created_at)

    def sync_comments(self, project, issue, jira_issue, comments=None):
        comments = self.client.comments(jira_issue["id"]) if comments is None else comments
        # deleted in Jira: removed here too (only comments that came from Jira; it can be restored)
        removed = (
            IssueComment.objects.filter(issue=issue, external_source=SOURCE)
            .exclude(external_id__in=[str(comment["id"]) for comment in comments])
            .delete()
        )
        if removed:
            self.count("comments_deleted", removed)
        for comment in comments:
            author = self.user_for(comment.get("author"), project)
            html = adf_to_html(comment.get("body"))
            if author is None:
                name = (comment.get("author") or {}).get("displayName") or "Jira user"
                html = f"<p><em>{name} (Jira)</em></p>{html}"
            mapping = self.get_map("comment", comment["id"])
            record = IssueComment.all_objects.filter(pk=mapping.plane_id).first() if mapping else None
            if record is None:
                record = IssueComment.objects.create(
                    issue=issue,
                    project=project,
                    workspace=self.workspace,
                    actor=author or self.actor,
                    comment_html=html,
                    external_source=SOURCE,
                    external_id=str(comment["id"]),
                )
                self.count("comments_created")
            elif record.deleted_at is None and (
                record.comment_html != html or (author is not None and record.actor_id != author.id)
            ):
                record.comment_html = html
                record.actor = author or record.actor
                record.save()
                self.count("comments_updated")
            dates = {
                "created_at": jira_datetime(comment.get("created")),
                "updated_at": jira_datetime(comment.get("updated")),
            }
            IssueComment.all_objects.filter(pk=record.pk).update(**{k: v for k, v in dates.items() if v})
            self.set_map("comment", comment["id"], record.id, jira_issue.get("key"))

    def sync_watchers(self, project, issue, jira_issue, watchers=None):
        try:
            watchers = self.client.watchers(jira_issue["id"]) if watchers is None else watchers
        except JiraError:
            return
        for watcher in watchers:
            user = self.user_for(watcher, project)
            if user:
                IssueSubscriber.objects.get_or_create(
                    issue=issue, subscriber=user, defaults={"project": project, "workspace": self.workspace}
                )

    @staticmethod
    def person_name(jira_user):
        return ((jira_user or {}).get("displayName") or "")[:255] or "Jira user"

    @staticmethod
    def history_rows(history):
        """The entries Jira's History tab shows for one change: (item index, field, label, old, new, verb)."""
        items = history.get("items") or []
        logged = ""
        for item in items:
            if (item.get("field") or "").lower() == "timespent":
                try:
                    delta = int(float(item.get("to") or 0)) - int(float(item.get("from") or 0))
                except (TypeError, ValueError):
                    delta = 0
                logged = format_duration(delta) if delta > 0 else ""
        rows = []
        for index, item in enumerate(items):
            jira_field = (item.get("field") or "").lower()
            label = jira_field_label(item.get("field"))
            if jira_field == "worklogid":
                # Jira shows a work log as "<person> logged 3h"
                if item.get("to"):
                    rows.append((index, "worklog", "Work Log", "", logged, "logged"))
                else:
                    rows.append((index, "worklog", "Work Log", logged, "", "deleted a work log"))
                continue
            field = HISTORY_FIELDS.get(jira_field, re.sub(r"[^a-z0-9]+", "_", jira_field).strip("_") or "field")
            old_value = item.get("fromString") or ""
            new_value = item.get("toString") or ""
            if jira_field in TIME_FIELDS:
                old_value = format_duration(item.get("from")) if item.get("from") not in (None, "") else ""
                new_value = format_duration(item.get("to")) if item.get("to") not in (None, "") else ""
            rows.append((index, field, label, str(old_value)[:20000], str(new_value)[:20000], "updated"))
        return rows

    def sync_history(self, project, issue, jira_issue, changelog=None):
        """Every entry of the Jira History tab: same person (also without an account here), date, time, field, values.

        Entries imported before are corrected too, so the history always matches Jira. Saved in bulk: an issue can
        have thousands of entries.
        """
        histories = self.client.changelog(jira_issue["id"]) if changelog is None else changelog
        wanted = {}
        for history in histories:
            author = self.user_for(history.get("author"), project)
            author_name = self.person_name(history.get("author")) if history.get("author") else "Jira"
            when = jira_datetime(history.get("created"))
            try:
                group_order = int(history["id"]) % 100
            except (TypeError, ValueError):
                group_order = 0
            for index, field, label, old_value, new_value, verb in self.history_rows(history):
                # keeps Jira's order of changes made in the same millisecond (less than 1 ms apart)
                moment = (when + timedelta(microseconds=group_order * 10 + min(index, 9))) if when else None
                values = {
                    "actor_id": author.id if author else None,
                    "verb": verb,
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                    "comment": f"{verb} the {label} in Jira" if verb == "updated" else f"{verb} in Jira",
                    "external_source": SOURCE,
                    "external_actor_name": author_name,
                    "external_field_name": label,
                }
                if moment:
                    values.update(created_at=moment, updated_at=moment)
                wanted[f"{history['id']}:{index}"] = (values, when)
        if not wanted:
            return
        maps = {
            record.jira_id: record
            for record in JiraEntityMap.objects.filter(
                workspace=self.workspace, entity_type="history", jira_id__in=list(wanted)
            )
        }
        activities = IssueActivity.objects.in_bulk([record.plane_id for record in maps.values()])
        fields = sorted({name for values, _ in wanted.values() for name in values})
        created, changed, remapped = [], [], []
        for key, (values, when) in wanted.items():
            record = maps.get(key)
            activity = activities.get(record.plane_id) if record else None
            if activity is None:
                activity = IssueActivity(
                    issue=issue,
                    project=project,
                    workspace=self.workspace,
                    epoch=int((when or timezone.now()).timestamp()),
                    created_by_id=self.actor.id,
                    **values,
                )
                created.append((key, record, activity))
            elif any(getattr(activity, name) != value for name, value in values.items()):
                for name, value in values.items():
                    setattr(activity, name, value)
                changed.append(activity)
        if created:
            IssueActivity.objects.bulk_create([activity for _, _, activity in created], batch_size=500)
            # bulk_create stamps "now" on created_at / updated_at: put Jira's moments back
            for key, _record, activity in created:
                values = wanted[key][0]
                activity.created_at = values.get("created_at", activity.created_at)
                activity.updated_at = values.get("updated_at", activity.updated_at)
            IssueActivity.objects.bulk_update(
                [activity for _, _, activity in created], ["created_at", "updated_at"], batch_size=500
            )
            new_maps = []
            for key, record, activity in created:
                if record is None:
                    new_maps.append(
                        JiraEntityMap(
                            workspace=self.workspace,
                            entity_type="history",
                            jira_id=key,
                            plane_id=activity.id,
                            jira_key=jira_issue.get("key") or "",
                        )
                    )
                else:  # its entry was removed here: point to the new one
                    record.plane_id = activity.id
                    remapped.append(record)
            JiraEntityMap.objects.bulk_create(new_maps, batch_size=500)
            JiraEntityMap.objects.bulk_update(remapped, ["plane_id"], batch_size=500)
            self.count("history_entries", len(created))
        if changed:
            IssueActivity.objects.bulk_update(changed, fields, batch_size=500)

    def sync_attachments(self, project, issue, jira_issue):
        from plane.settings.storage import S3Storage

        storage = None
        for attachment in (jira_issue.get("fields") or {}).get("attachment") or []:
            if self.get_map("attachment", attachment["id"]):
                continue
            # Jira files are copied whatever their size (the upload limit is for people uploading here),
            # streamed from Jira straight into storage so big videos never sit in memory
            size = int(attachment.get("size") or 0)
            name = attachment.get("filename") or "attachment"
            mime = attachment.get("mimeType") or "application/octet-stream"
            key = asset_storage_key(
                name, entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT, workspace_id=self.workspace.id
            )
            storage = storage or S3Storage(request=None)
            stored = False
            for _attempt in range(3):
                try:
                    with self.client.attachment_stream(attachment["content"]) as stream:
                        stored = storage.upload_file(stream, key, mime)
                except JiraError as error:
                    if error.status_code in (401, 403, 404):
                        break  # gone or not visible in Jira: nothing to copy
                except Exception as error:  # a dropped connection: try again
                    logger.warning("Jira attachment %s: %s", attachment.get("id"), error)
                if stored:
                    break
            if not stored:
                self.warn(f"{jira_issue.get('key')}: attachment '{name}' could not be copied from Jira.")
                continue
            asset = FileAsset.objects.create(
                attributes={"name": name, "type": mime, "size": size},
                asset=key,
                size=size,
                workspace=self.workspace,
                project_id=project.id,
                issue=issue,
                entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
                created_by=self.user_for(attachment.get("author"), project) or self.actor,
                is_uploaded=True,
                external_source=SOURCE,
                external_id=str(attachment["id"]),
            )
            self.set_map("attachment", attachment["id"], asset.id, jira_issue.get("key"))
            self.count("attachments_copied")

    # ---- custom fields (the fields on the right of a Jira issue) -----------------------------------------------
    def field_meta(self):
        if self.jira_fields is None:
            try:
                self.jira_fields = {field["id"]: field for field in self.client.fields()}
            except JiraError as error:
                self.warn(f"Custom fields not imported ({error}).")
                self.jira_fields = {}
        return self.jira_fields

    def custom_field_for(self, project, field_id, name, kind):
        mapping = self.get_map("field", f"{project.id}:{field_id}")
        field = CustomField.objects.filter(pk=mapping.plane_id).first() if mapping else None
        if field is None:
            field = CustomField.objects.filter(project=project, name=name[:255]).first()
            if field is not None and field.field_type != kind and field.external_id != field_id:
                field = None
                name = f"{name} (Jira)"
            if field is None:
                last = CustomField.objects.filter(project=project).aggregate(last=Max("sort_order"))["last"] or 0
                field = CustomField.objects.create(
                    project=project,
                    workspace=self.workspace,
                    name=name[:255],
                    field_type=kind,
                    sort_order=last + 10000,
                    external_source=SOURCE,
                    external_id=field_id,
                )
                self.count("custom_fields_created")
            self.set_map("field", f"{project.id}:{field_id}", field.id, name)
        return field

    def sync_custom_fields(self, project, issue, fields):
        meta = self.field_meta()
        for field_id, raw in fields.items():
            if field_id in SKIP_FIELDS:
                continue
            info = meta.get(field_id) or {}
            if not info and field_id not in TIME_TRACKING_FIELDS:
                continue
            custom_type = ((info.get("schema") or {}).get("custom") or "").lower()
            if custom_type in SKIP_SCHEMAS or any(word in custom_type for word in INTERNAL_FIELD_WORDS):
                continue
            if (info.get("name") or "").strip().lower() in INTERNAL_FIELD_NAMES:
                continue
            if not info.get("custom") and field_id not in TIME_TRACKING_FIELDS and field_id not in SYSTEM_FIELD_NAMES:
                continue
            name = (
                TIME_TRACKING_FIELDS.get(field_id) or SYSTEM_FIELD_NAMES.get(field_id) or info.get("name") or field_id
            )
            converted = jira_custom_value(field_id, info, raw)
            mapping = self.get_map("field", f"{project.id}:{field_id}")
            if converted is None:
                if mapping:
                    CustomFieldValue.objects.filter(issue=issue, field_id=mapping.plane_id).delete(soft=False)
                continue
            kind, value = converted
            field = self.custom_field_for(project, field_id, name, kind)
            value = coerce_value(field.field_type, kind, value)
            if value is None or value == []:
                continue
            new_options = value if isinstance(value, list) else [value]
            if field.field_type in ("select", "multi_select"):
                missing = [str(option) for option in new_options if str(option) not in field.options]
                if missing:
                    field.options = [*field.options, *missing]
                    field.save(update_fields=["options", "updated_at"])
            CustomFieldValue.objects.update_or_create(
                issue=issue,
                field=field,
                defaults={"value": value, "project": project, "workspace": self.workspace},
            )
            self.count("custom_values")

        # Jira's Reporter (always) and Assignee when that person has no account here: names as in Jira
        reporter = fields.get("reporter") or fields.get("creator")
        self.set_name_field(project, issue, "reporter", "Reporter", self.person_name(reporter) if reporter else "")
        assignee = fields.get("assignee")
        unmatched = assignee and self.user_for(assignee, None) is None
        self.set_name_field(
            project, issue, "assignee", "Assignee (Jira)", self.person_name(assignee) if unmatched else ""
        )

    def set_name_field(self, project, issue, field_id, name, text):
        mapping = self.get_map("field", f"{project.id}:{field_id}")
        if not text:
            if mapping:
                CustomFieldValue.objects.filter(issue=issue, field_id=mapping.plane_id).delete(soft=False)
            return
        field = self.custom_field_for(project, field_id, name, "text")
        CustomFieldValue.objects.update_or_create(
            issue=issue, field=field, defaults={"value": text, "project": project, "workspace": self.workspace}
        )

    # ---- relations (second pass) --------------------------------------------------------------------------------
    def plane_issue_id(self, jira_issue_id):
        mapping = self.get_map("issue", jira_issue_id)
        return mapping.plane_id if mapping else None

    def link_issues(self, project, jira_issue, issue_cycle, modules):
        fields = jira_issue.get("fields") or {}
        issue_id = self.plane_issue_id(jira_issue["id"])
        if issue_id is None:
            return
        parent = fields.get("parent")
        parent_id = self.plane_issue_id(parent["id"]) if parent else None
        Issue.objects.filter(pk=issue_id).exclude(parent_id=parent_id).update(parent_id=parent_id)

        for link in fields.get("issuelinks") or []:
            link_type = ((link.get("type") or {}).get("name") or "").lower()
            if "outwardIssue" in link:
                other, outward = link["outwardIssue"], True
            elif "inwardIssue" in link:
                other, outward = link["inwardIssue"], False
            else:
                continue
            other_id = self.plane_issue_id(other.get("id"))
            if other_id is None:
                continue
            if "block" in link_type:
                # "A blocks B" -> B is blocked by A
                blocked, blocker, relation = (
                    (other_id, issue_id, "blocked_by") if outward else (issue_id, other_id, "blocked_by")
                )
            elif "duplicat" in link_type:
                blocked, blocker, relation = issue_id, other_id, "duplicate"
            else:
                blocked, blocker, relation = issue_id, other_id, "relates_to"
            exists = IssueRelation.objects.filter(
                issue_id__in=[blocked, blocker], related_issue_id__in=[blocked, blocker]
            ).exists()
            if not exists:
                try:
                    IssueRelation.objects.create(
                        issue_id=blocked,
                        related_issue_id=blocker,
                        relation_type=relation,
                        project=project,
                        workspace=self.workspace,
                        created_by=self.actor,
                    )
                    self.count("links_created")
                except IntegrityError:
                    pass

        cycle = issue_cycle.get(str(jira_issue["id"]))
        if cycle is not None:
            record = CycleIssue.objects.filter(issue_id=issue_id).first()
            if record is None:
                CycleIssue.objects.create(issue_id=issue_id, cycle=cycle, project=project, workspace=self.workspace)
            elif record.cycle_id != cycle.id:
                record.cycle = cycle
                record.save(update_fields=["cycle", "updated_at"])
        wanted = {
            module.id for module in (modules.get(str(c.get("id"))) for c in fields.get("components") or []) if module
        }
        # components taken off the work item in Jira (modules made here by people are left alone)
        ModuleIssue.objects.filter(issue_id=issue_id, module_id__in=[module.id for module in modules.values()]).exclude(
            module_id__in=wanted
        ).delete()
        for module_id in wanted:
            if not ModuleIssue.objects.filter(issue_id=issue_id, module_id=module_id).exists():
                ModuleIssue.objects.create(
                    issue_id=issue_id, module_id=module_id, project=project, workspace=self.workspace
                )

    # ---- keys: SHOP-57 in Jira is SHOP-57 here ---------------------------------------------------------------------
    def align_numbers(self, project, jira_issues):
        """Give every imported work item the number of its Jira key, so keys match Jira exactly."""
        targets = {}
        for jira_issue in jira_issues:
            match = re.search(r"-(\d+)$", jira_issue.get("key") or "")
            plane_id = self.plane_issue_id(jira_issue["id"])
            if match and plane_id:
                targets[plane_id] = int(match.group(1))
        if not targets:
            return
        current = dict(Issue.all_objects.filter(project=project).values_list("id", "sequence_id"))
        wanted = set(targets.values())
        with transaction.atomic():
            # work items created here that hold a Jira number move after the highest number
            next_free = max([*wanted, *current.values(), 0]) + 1
            for issue_id, number in current.items():
                if issue_id not in targets and number in wanted:
                    Issue.all_objects.filter(pk=issue_id).update(sequence_id=next_free)
                    IssueSequence.objects.filter(issue_id=issue_id).update(sequence=next_free)
                    next_free += 1
            changed = 0
            for issue_id, number in targets.items():
                if current.get(issue_id) != number:
                    Issue.all_objects.filter(pk=issue_id).update(sequence_id=number)
                    IssueSequence.objects.filter(issue_id=issue_id).update(sequence=number)
                    changed += 1
            # new work items continue after the highest number
            highest = max([*wanted, next_free - 1])
            if not IssueSequence.objects.filter(project=project, sequence__gte=highest).exists():
                IssueSequence.objects.create(project=project, workspace=self.workspace, sequence=highest, deleted=True)
        if changed:
            self.count("keys_aligned", changed)

    # ---- one project ------------------------------------------------------------------------------------------
    def import_project(self, project_key):
        self.since = None
        jira_project = self.client.project(project_key)
        if not self.client.can_browse(project_key):
            raise JiraError(
                f"the connected Jira account ({self.connection_name()}) has no 'Browse projects' permission here, "
                "so Jira shows none of its work items. Give that account access in Jira and sync again"
            )
        self.save_progress(f"{project_key}: project and statuses")
        started_at = timezone.now()
        project, synced_at = self.project_for(jira_project)
        # synced before: only work items changed in Jira since then (a full re-sync reads them all)
        self.since = None if self.options["full"] or synced_at is None else synced_at - SYNC_OVERLAP
        self.new_projects[project_key] = {"project_id": str(project.id), "name": project.name}
        # only Jira Software projects have boards and sprints (business projects do not)
        is_software = jira_project.get("projectTypeKey", "software") == "software"

        if self.since is None:
            states = self.states_for(project, project_key)
            types = ensure_project_work_item_types(project)
            self.save_progress(f"{project_key}: sprints and components")
            issue_cycle = self.sprints_for(project, project_key) if is_software else {}
            modules = self.modules_for(project, jira_project)
            self.sync_project_people(project, project_key)
            pages = iter(self.client.issues(project_key))
        else:
            # only the work items changed in Jira since the last sync (any change, also one only in their history);
            # Jira's JQL dates are in the connected account's time zone; minutes ago are the same everywhere
            minutes = int((timezone.now() - self.since).total_seconds() // 60) + 1
            self.save_progress(f"{project_key}: work items changed since {self.since:%d %b %Y %H:%M} UTC")
            changed = list(self.client.issues(project_key, updated_within_minutes=minutes))
            if changed:
                states = self.states_for(project, project_key)
                types = ensure_project_work_item_types(project)
                # sprints of the changed work items only (not every sprint of every board); people on them join the
                # project as they are read (project roles follow Jira on a user sync or a full re-sync)
                issue_cycle = self.sprints_of_issues(project, changed) if is_software else {}
                modules = self.modules_for(project, jira_project)
            pages = iter(changed)
        jira_issues = []
        with ThreadPoolExecutor(READ_THREADS) as pool:
            while batch := list(islice(pages, READ_AHEAD)):
                details = self.read_details(pool, batch)
                for jira_issue in batch:
                    self.sync_issue(project, jira_issue, states, types, details.get(jira_issue["id"], {}))
                    jira_issues.append(jira_issue)
                    self.items_done = len(jira_issues)
                    if time.monotonic() - self.last_saved > 5:
                        self.save_progress(f"{project_key}: {self.items_done} work items")
        self.save_progress(f"{project_key}: {len(jira_issues)} work items")
        if jira_issues:
            self.save_progress(f"{project_key}: keys, parents, links and sprints")
            self.align_numbers(project, jira_issues)
            for jira_issue in jira_issues:
                self.link_issues(project, jira_issue, issue_cycle, modules)
        self.count("issues_seen", len(jira_issues))
        # the next sync reads what changes in Jira from now on (only after the whole project is saved)
        JiraEntityMap.objects.filter(
            workspace=self.workspace, entity_type="project", jira_id=str(jira_project["id"])
        ).update(jira_updated=started_at.isoformat())
        self.save_progress(f"{project_key}: done")
        self.since = None

    def sync_issue(self, project, jira_issue, states, types, details):
        issue, changed = self.upsert_issue(project, jira_issue, states, types)
        if issue is None or not changed:
            return

        def read(name):
            # read ahead in parallel; read now when it was not (or the parallel read failed the same way)
            if name not in details:
                return getattr(self.client, name)(jira_issue["id"])
            ok, value = details[name]
            if not ok:
                raise value
            return value

        if self.options["comments"]:
            self.sync_comments(project, issue, jira_issue, comments=read("comments"))
        try:
            watchers = read("watchers")
        except JiraError:
            watchers = []
        self.sync_watchers(project, issue, jira_issue, watchers=watchers)
        if self.options["history"]:
            self.sync_history(project, issue, jira_issue, changelog=read("changelog"))
        if self.options["attachments"]:
            self.sync_attachments(project, issue, jira_issue)
        JiraEntityMap.objects.filter(
            workspace=self.workspace, entity_type="issue", jira_id=str(jira_issue["id"])
        ).update(jira_updated=(jira_issue.get("fields") or {}).get("updated") or "")

    def needs_details(self, jira_issue):
        """Whether the work item changed in Jira since the last sync (only those are read again)."""
        if self.options["full"]:
            return True
        mapping = self.get_map("issue", jira_issue["id"])
        updated = (jira_issue.get("fields") or {}).get("updated") or ""
        return not (mapping and mapping.jira_updated and mapping.jira_updated == updated)

    def read_details(self, pool, jira_issues):
        """{issue id: {name: (ok, value)}}: comments, history and watchers read from Jira in parallel."""
        if not hasattr(self.client, "clone"):
            return {}
        names = ["watchers"]
        if self.options["comments"]:
            names.append("comments")
        if self.options["history"]:
            names.append("changelog")
        jobs = [(item["id"], name) for item in jira_issues if self.needs_details(item) for name in names]
        local = self.read_local

        def fetch(job):
            if not hasattr(local, "client"):
                local.client = self.client.clone()
            issue_id, name = job
            try:
                return job, (True, getattr(local.client, name)(issue_id))
            except Exception as error:  # raised again when the work item is saved
                return job, (False, error)

        details = {}
        for (issue_id, name), outcome in pool.map(fetch, jobs):
            details.setdefault(issue_id, {})[name] = outcome
        return details

    def connection_name(self):
        connection = JiraConnection.objects.filter(workspace=self.workspace).first()
        return (connection.account_name or connection.email) if connection else "Jira"

    def run_all(self):
        # records are saved as the person who started the sync (there is no web request in the worker)
        with impersonate(self.actor):
            self._run_all()

    def sync_project(self, project_key):
        """One project of a run (the background workers call this for each project in turn)."""
        self.project_key = project_key
        with impersonate(self.actor):
            self.import_project(project_key)

    def _run_all(self):
        if self.options.get("kind") == "users":
            self.sync_users()
            return
        for project_key in self.run.project_keys:
            try:
                self.import_project(project_key)
            except JiraError as error:
                self.warn(f"{project_key}: {error}")
                logger.warning("Jira import of %s failed: %s", project_key, error)
        self.save_progress("Finished")
