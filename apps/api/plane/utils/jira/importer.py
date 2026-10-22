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
import uuid
from datetime import datetime, timedelta

import pytz

from crum import impersonate
from django.conf import settings
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
    JiraEntityMap,
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


class JiraImporter:
    def __init__(self, run, client, workspace, actor):
        self.run = run
        self.client = client
        self.workspace = workspace
        self.actor = actor
        self.options = {"attachments": True, "history": True, "comments": True, "full": False, **(run.options or {})}
        self.stats = run.stats or {}
        self.user_cache = {}
        self.unmatched = {entry.get("account_id"): entry for entry in run.unmatched_users or []}
        self.jira_fields = None
        self.group_cache = {}
        self.members = list(
            WorkspaceMember.objects.filter(workspace=workspace, is_active=True, member__is_bot=False).select_related(
                "member"
            )
        )

    # ---- helpers --------------------------------------------------------------------------------------------------
    def count(self, key, amount=1):
        self.stats[key] = self.stats.get(key, 0) + amount

    def warn(self, message):
        if len(self.run.warnings) < 200:
            self.run.warnings.append(message)

    def save_progress(self, step=None):
        if step:
            self.run.current_step = step
        self.run.stats = self.stats
        self.run.unmatched_users = list(self.unmatched.values())
        self.run.save(update_fields=["current_step", "stats", "warnings", "unmatched_users", "projects", "updated_at"])

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
        """Every active Jira person gets an account (same name, email, avatar, time zone) in this workspace."""
        self.save_progress("Reading Jira users")
        people = [
            person
            for person in self.client.users()
            if person.get("accountType") == "atlassian" and person.get("active") and person.get("accountId")
        ]
        admins = self.jira_admin_ids()
        self.save_progress(f"Adding {len(people)} users")
        for person in people:
            email = (person.get("emailAddress") or "").strip().lower()
            name = (person.get("displayName") or "").strip()
            if not email:
                self.count("users_without_email")
                self.warn(f"{name or person['accountId']}: Jira hides this person's email, no account made")
                continue
            role = ADMIN if person["accountId"] in admins else MEMBER
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                first, _, last = name.partition(" ")
                timezone_name = person.get("timeZone") if person.get("timeZone") in TIMEZONES else "UTC"
                user = User(
                    email=email,
                    username=uuid.uuid4().hex,
                    display_name=name or email.split("@")[0],
                    first_name=first[:255],
                    last_name=last[:255],
                    avatar=(person.get("avatarUrls") or {}).get("48x48", ""),
                    user_timezone=timezone_name,
                    is_password_autoset=True,
                    is_email_verified=True,
                )
                user.set_password(uuid.uuid4().hex)
                user.save()
                self.count("users_created")
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
            elif not membership.is_active or membership.role < role:
                # Jira admins are raised to Admin; nobody is lowered
                membership.is_active, membership.role = True, max(membership.role, role)
                membership.save(update_fields=["is_active", "role", "updated_at"])
                self.count("users_added")
            else:
                self.count("users_existing")
            self.set_map("user", person["accountId"], str(user.id), jira_key=email)
            self.unmatched.pop(person["accountId"], None)
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
                self.save_progress(f"{mapped.jira_key or project.name}: project roles")
                self.sync_project_roles(project, mapped.jira_key or mapped.jira_id)
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
        mapping = self.get_map("project", jira_project["id"])
        project = Project.objects.filter(pk=mapping.plane_id, workspace=self.workspace).first() if mapping else None
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
        self.set_map("project", jira_project["id"], project.id, jira_project.get("key"))
        lead = self.user_for(jira_project.get("lead"), project)
        if lead and project.project_lead_id != lead.id:
            project.project_lead = lead
            project.save(update_fields=["project_lead", "updated_at"])
        return project

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
        rank = {"closed": 0, "future": 1, "active": 2}
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
                try:
                    issue_ids = self.client.sprint_issue_ids(sprint["id"])
                except JiraError:
                    issue_ids = []
                for issue_id in issue_ids:
                    current = issue_cycle.get(str(issue_id))
                    order = (rank.get(sprint.get("state"), 0), values["start_date"] or timezone.now())
                    if current is None or order > current[0]:
                        issue_cycle[str(issue_id)] = (order, cycle)
        return {issue_id: value[1] for issue_id, value in issue_cycle.items()}

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
        self.set_map("issue", jira_issue["id"], issue.id, jira_issue.get("key"), fields.get("updated") or "")
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

    def sync_comments(self, project, issue, jira_issue):
        for comment in self.client.comments(jira_issue["id"]):
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
            elif record.deleted_at is None and record.comment_html != html:
                record.comment_html = html
                record.save()
                self.count("comments_updated")
            dates = {
                "created_at": jira_datetime(comment.get("created")),
                "updated_at": jira_datetime(comment.get("updated")),
            }
            IssueComment.all_objects.filter(pk=record.pk).update(**{k: v for k, v in dates.items() if v})
            self.set_map("comment", comment["id"], record.id, jira_issue.get("key"))

    def sync_watchers(self, project, issue, jira_issue):
        try:
            watchers = self.client.watchers(jira_issue["id"])
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

    def sync_history(self, project, issue, jira_issue):
        """Every entry of the Jira History tab: same person (also without an account here), date, time, field, values.

        Entries imported before are corrected too, so the history always matches Jira.
        """
        for history in self.client.changelog(jira_issue["id"]):
            author = self.user_for(history.get("author"), None)
            author_name = self.person_name(history.get("author")) if history.get("author") else "Jira"
            when = jira_datetime(history.get("created"))
            try:
                group_order = int(history["id"]) % 100
            except (TypeError, ValueError):
                group_order = 0
            for index, field, label, old_value, new_value, verb in self.history_rows(history):
                key = f"{history['id']}:{index}"
                # keeps Jira's order of changes made in the same millisecond (less than 1 ms apart)
                moment = (when + timedelta(microseconds=group_order * 10 + min(index, 9))) if when else None
                values = {
                    "actor": author,
                    "verb": verb,
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                    "comment": f"{verb} the {label} in Jira" if verb == "updated" else f"{verb} in Jira",
                    "external_source": SOURCE,
                    "external_actor_name": author_name,
                    "external_field_name": label,
                }
                existing = self.get_map("history", key)
                activity = IssueActivity.objects.filter(pk=existing.plane_id).first() if existing else None
                if activity is None:
                    activity = IssueActivity.objects.create(
                        issue=issue,
                        project=project,
                        workspace=self.workspace,
                        epoch=int((when or timezone.now()).timestamp()),
                        **values,
                    )
                    self.set_map("history", key, activity.id, jira_issue.get("key"))
                    self.count("history_entries")
                if moment:
                    values.update(created_at=moment, updated_at=moment)
                IssueActivity.objects.filter(pk=activity.pk).update(**values)

    def sync_attachments(self, project, issue, jira_issue):
        from plane.settings.storage import S3Storage

        storage = None
        for attachment in (jira_issue.get("fields") or {}).get("attachment") or []:
            if self.get_map("attachment", attachment["id"]):
                continue
            size = int(attachment.get("size") or 0)
            if size > settings.FILE_SIZE_LIMIT:
                self.warn(
                    f"{jira_issue.get('key')}: attachment '{attachment.get('filename')}' "
                    "is larger than the upload limit."
                )
                continue
            try:
                content = self.client.attachment_content(attachment["content"])
            except JiraError as error:
                self.warn(f"{jira_issue.get('key')}: attachment '{attachment.get('filename')}' not copied ({error}).")
                continue
            name = attachment.get("filename") or "attachment"
            mime = attachment.get("mimeType") or "application/octet-stream"
            key = asset_storage_key(
                name, entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT, workspace_id=self.workspace.id
            )
            storage = storage or S3Storage(request=None)
            if not storage.upload_file(io.BytesIO(content), key, mime):
                self.warn(f"{jira_issue.get('key')}: attachment '{name}' could not be stored.")
                continue
            asset = FileAsset.objects.create(
                attributes={"name": name, "type": mime, "size": len(content)},
                asset=key,
                size=len(content),
                workspace=self.workspace,
                project_id=project.id,
                issue=issue,
                entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
                created_by=self.user_for(attachment.get("author"), None) or self.actor,
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
        for component in fields.get("components") or []:
            module = modules.get(str(component.get("id")))
            if module and not ModuleIssue.objects.filter(issue_id=issue_id, module=module).exists():
                ModuleIssue.objects.create(issue_id=issue_id, module=module, project=project, workspace=self.workspace)

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
        jira_project = self.client.project(project_key)
        self.save_progress(f"{project_key}: project and statuses")
        project = self.project_for(jira_project)
        self.run.projects[project_key] = {"project_id": str(project.id), "name": project.name}
        states = self.states_for(project, project_key)
        types = ensure_project_work_item_types(project)
        self.save_progress(f"{project_key}: sprints and components")
        issue_cycle = self.sprints_for(project, project_key)
        modules = self.modules_for(project, jira_project)
        self.sync_project_roles(project, project_key)

        jira_issues = []
        for index, jira_issue in enumerate(self.client.issues(project_key), start=1):
            issue, changed = self.upsert_issue(project, jira_issue, states, types)
            if issue is not None and changed:
                if self.options["comments"]:
                    self.sync_comments(project, issue, jira_issue)
                self.sync_watchers(project, issue, jira_issue)
                if self.options["history"]:
                    self.sync_history(project, issue, jira_issue)
                if self.options["attachments"]:
                    self.sync_attachments(project, issue, jira_issue)
            jira_issues.append(jira_issue)
            if index % 25 == 0:
                self.save_progress(f"{project_key}: {index} issues")
        self.save_progress(f"{project_key}: keys, parents, links and sprints")
        self.align_numbers(project, jira_issues)
        for jira_issue in jira_issues:
            self.link_issues(project, jira_issue, issue_cycle, modules)
        self.count("issues_seen", len(jira_issues))
        self.save_progress(f"{project_key}: done")

    def run_all(self):
        # records are saved as the person who started the sync (there is no web request in the worker)
        with impersonate(self.actor):
            self._run_all()

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
