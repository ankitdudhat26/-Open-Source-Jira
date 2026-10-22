# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Jira import (read only) and the workspace change history."""

# Django imports
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.bgtasks.jira_sync_task import jira_sync_task
from plane.db.models import (
    IssueActivity,
    JiraConnection,
    JiraEntityMap,
    JiraSyncRun,
    Project,
    ProjectMember,
    Workspace,
    WorkspaceMember,
)
from plane.license.utils.encryption import decrypt_data, encrypt_data
from plane.utils.jira.client import (
    AtlassianAdminClient,
    JiraClient,
    JiraError,
    normalize_site_url,
    parse_user_export,
)
from plane.utils.uuid import is_valid_uuid

SYNC_OPTIONS = ("attachments", "history", "comments", "full")


def serialize_connection(connection):
    if connection is None:
        return {"connected": False}
    return {
        "connected": True,
        "site_url": connection.site_url,
        "email": connection.email,
        "account_name": connection.account_name,
        "verified_at": connection.verified_at,
        "has_admin_api_key": bool(connection.admin_api_key),
        "org_name": connection.org_name,
    }


def serialize_run(run):
    return {
        "id": str(run.id),
        "status": run.status,
        "project_keys": run.project_keys,
        "options": {key: value for key, value in (run.options or {}).items() if key != "directory"},
        "current_step": run.current_step,
        "stats": run.stats,
        "projects": run.projects,
        "warnings": run.warnings,
        "unmatched_users": run.unmatched_users,
        "error": run.error,
        "initiated_by": str(run.initiated_by_id) if run.initiated_by_id else None,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


class JiraConnectionEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        connection = JiraConnection.objects.filter(workspace__slug=slug).first()
        return Response(serialize_connection(connection), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        """Save the credentials after checking them against Jira (a read only call)."""
        workspace = Workspace.objects.get(slug=slug)
        connection = JiraConnection.objects.filter(workspace=workspace).first()
        email = str(request.data.get("email") or "").strip()
        token = str(request.data.get("api_token") or "").strip()
        if not token and connection:
            token = decrypt_data(connection.api_token)
        try:
            site_url = normalize_site_url(request.data.get("site_url"))
            if not email or not token:
                raise JiraError("Email and API token are required.")
            account = JiraClient(site_url, email, token).myself()
        except JiraError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        # optional organization admin API key: "" keeps the saved one, "-" removes it
        admin_key = str(request.data.get("admin_api_key") or "").strip()
        org = {}
        if admin_key == "-":
            org = {"admin_api_key": "", "org_id": "", "org_name": ""}
        elif admin_key:
            try:
                orgs = AtlassianAdminClient(admin_key).orgs()
            except JiraError as error:
                return Response({"error": f"Organization admin API key: {error}"}, status=status.HTTP_400_BAD_REQUEST)
            if not orgs:
                return Response(
                    {"error": "That admin API key has no organization."}, status=status.HTTP_400_BAD_REQUEST
                )
            org = {"admin_api_key": encrypt_data(admin_key), "org_id": orgs[0]["id"], "org_name": orgs[0]["name"]}
        values = {
            **org,
            "site_url": site_url,
            "email": email,
            "api_token": encrypt_data(token),
            "account_name": account.get("displayName") or email,
            "verified_at": timezone.now(),
            "updated_by": request.user,
        }
        if connection:
            for key, value in values.items():
                setattr(connection, key, value)
            connection.save()
        else:
            connection = JiraConnection.objects.create(workspace=workspace, created_by=request.user, **values)
        return Response(serialize_connection(connection), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug):
        """Forget the credentials. Imported projects and work items stay."""
        JiraConnection.objects.filter(workspace__slug=slug).delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


def client_for(slug):
    connection = JiraConnection.objects.filter(workspace__slug=slug).first()
    if connection is None:
        raise JiraError("Connect Jira first.")
    return JiraClient(connection.site_url, connection.email, decrypt_data(connection.api_token))


class JiraProjectsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        try:
            jira_projects = client_for(slug).projects()
        except JiraError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        workspace = Workspace.objects.get(slug=slug)
        links = {
            record.jira_id: record
            for record in JiraEntityMap.objects.filter(workspace=workspace, entity_type="project")
        }
        projects = {
            str(project.id): project
            for project in Project.objects.filter(pk__in=[link.plane_id for link in links.values()])
        }
        last_runs = {}
        for run in JiraSyncRun.objects.filter(workspace=workspace, status="completed").order_by("-finished_at")[:50]:
            for key in run.project_keys:
                last_runs.setdefault(key, run.finished_at)
        result = []
        for item in jira_projects:
            link = links.get(str(item.get("id")))
            project = projects.get(str(link.plane_id)) if link else None
            result.append(
                {
                    "id": str(item.get("id")),
                    "key": item.get("key"),
                    "name": item.get("name"),
                    "type": item.get("projectTypeKey"),
                    "lead": (item.get("lead") or {}).get("displayName"),
                    "linked_project": (
                        {"id": str(project.id), "name": project.name, "identifier": project.identifier}
                        if project
                        else None
                    ),
                    "last_synced_at": last_runs.get(item.get("key")),
                }
            )
        return Response(result, status=status.HTTP_200_OK)


class JiraSyncEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        runs = JiraSyncRun.objects.filter(workspace__slug=slug).order_by("-created_at")[:20]
        return Response([serialize_run(run) for run in runs], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        if not JiraConnection.objects.filter(workspace=workspace).exists():
            return Response({"error": "Connect Jira first."}, status=status.HTTP_400_BAD_REQUEST)
        # kind "users": add every active Jira person to the workspace instead of importing projects
        user_sync = request.data.get("kind") == "users"
        keys = [] if user_sync else request.data.get("project_keys")
        if not user_sync and (
            not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key.strip() for key in keys)
        ):
            return Response({"error": "Select at least one Jira project."}, status=status.HTTP_400_BAD_REQUEST)
        if JiraSyncRun.objects.filter(workspace=workspace, status__in=("queued", "running")).exists():
            return Response(
                {"error": "A sync is already running. Wait for it to finish."}, status=status.HTTP_409_CONFLICT
            )
        options = request.data.get("options") or {}
        options = {key: bool(options[key]) for key in SYNC_OPTIONS if key in options}
        if user_sync:
            options = {"kind": "users"}
            if request.data.get("users_file"):
                try:
                    options["directory"] = parse_user_export(str(request.data["users_file"]))
                except JiraError as error:
                    return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        run = JiraSyncRun.objects.create(
            workspace=workspace,
            initiated_by=request.user,
            project_keys=list(dict.fromkeys(key.strip() for key in keys)),
            options=options,
            created_by=request.user,
        )
        jira_sync_task.delay(str(run.id))
        return Response(serialize_run(run), status=status.HTTP_201_CREATED)


class JiraSyncRunEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, run_id):
        run = JiraSyncRun.objects.filter(workspace__slug=slug, pk=run_id).first()
        if run is None:
            return Response({"error": "Sync not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_run(run), status=status.HTTP_200_OK)


class WorkspaceHistoryEndpoint(BaseAPIView):
    """Every change to work items in the workspace: who changed what, when (including history imported from Jira)."""

    PAGE_SIZE = 50

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        is_admin = WorkspaceMember.objects.filter(
            workspace=workspace, member=request.user, is_active=True, role=ROLE.ADMIN.value
        ).exists()
        activities = IssueActivity.objects.filter(
            workspace=workspace, issue__isnull=False, project__archived_at__isnull=True
        )
        if not is_admin:
            member_projects = ProjectMember.objects.filter(
                workspace=workspace, member=request.user, is_active=True
            ).values_list("project_id", flat=True)
            activities = activities.filter(project_id__in=member_projects)

        params = request.query_params
        if is_valid_uuid(params.get("project_id", "")):
            activities = activities.filter(project_id=params["project_id"])
        if is_valid_uuid(params.get("actor_id", "")):
            activities = activities.filter(actor_id=params["actor_id"])
        if params.get("field"):
            field = params["field"]
            activities = (
                activities.filter(field__isnull=True, verb="created")
                if field == "created"
                else (activities.filter(field=field))
            )
        if params.get("source") == "jira":
            activities = activities.filter(
                Q(external_source="jira") | Q(comment__endswith="in Jira") | Q(comment__startswith="imported")
            )
        if parse_date(params.get("from") or ""):
            activities = activities.filter(created_at__date__gte=parse_date(params["from"]))
        if parse_date(params.get("to") or ""):
            activities = activities.filter(created_at__date__lte=parse_date(params["to"]))
        if params.get("search"):
            search = params["search"].strip()
            activities = activities.filter(Q(issue__name__icontains=search) | Q(comment__icontains=search))

        try:
            page = max(int(params.get("page", 1)), 1)
        except ValueError:
            page = 1
        start = (page - 1) * self.PAGE_SIZE
        rows = list(
            activities.select_related("actor", "project", "issue").order_by("-created_at")[
                start : start + self.PAGE_SIZE + 1
            ]
        )
        has_more = len(rows) > self.PAGE_SIZE
        return Response(
            {
                "results": [
                    {
                        "id": str(activity.id),
                        "created_at": activity.created_at,
                        "actor": (
                            {
                                "id": str(activity.actor_id),
                                "display_name": activity.actor.display_name,
                                "avatar_url": activity.actor.avatar_url,
                            }
                            if activity.actor_id
                            else None
                        ),
                        "project": {
                            "id": str(activity.project_id),
                            "name": activity.project.name,
                            "identifier": activity.project.identifier,
                        },
                        "issue": {
                            "id": str(activity.issue_id),
                            "sequence_id": activity.issue.sequence_id,
                            "name": activity.issue.name,
                        },
                        "verb": activity.verb,
                        "field": activity.field,
                        "old_value": activity.old_value,
                        "new_value": activity.new_value,
                        "comment": activity.comment,
                        # the person / field name in Jira (also when that person has no account here)
                        "actor_name": activity.external_actor_name,
                        "field_label": activity.external_field_name,
                        "from_jira": activity.external_source == "jira"
                        or activity.comment.endswith("in Jira")
                        or activity.comment.startswith("imported"),
                    }
                    for activity in rows[: self.PAGE_SIZE]
                ],
                "page": page,
                "has_more": has_more,
            },
            status=status.HTTP_200_OK,
        )
