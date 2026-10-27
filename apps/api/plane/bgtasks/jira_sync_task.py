# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import logging

from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from plane.db.models import JiraConnection, JiraEntityMap, JiraSyncRun
from plane.license.utils.encryption import decrypt_data
from plane.utils.exception_logger import log_exception
from plane.utils.jira.client import AtlassianAdminClient, JiraClient, JiraError
from plane.utils.jira.importer import JiraImporter, JiraSyncStopped, last_synced_at

logger = logging.getLogger("plane.worker")


# projects synced at the same time (each by its own task, so no task comes near the time limit)
LANES = 3
# a project whose worker gave no sign of life for this long was interrupted (worker restart, deploy, crash)
STALE_AFTER = timedelta(minutes=30)
MAX_ATTEMPTS = 3


def client_for(connection):
    return JiraClient(connection.site_url, connection.email, decrypt_data(connection.api_token))


@shared_task
def jira_sync_task(run_id):
    """Start a sync run (Jira is only read). A user sync runs here; projects are handed to parallel lanes."""
    run = JiraSyncRun.objects.filter(pk=run_id).select_related("workspace", "initiated_by").first()
    if run is None or run.status != "queued":
        return
    run.status = "running"
    run.started_at = timezone.now()
    run.current_step = "Connecting to Jira"
    run.save(update_fields=["status", "started_at", "current_step", "updated_at"])
    try:
        connection = JiraConnection.objects.get(workspace=run.workspace)
        client = client_for(connection)
        if run.options.get("kind") == "users":
            try:
                JiraImporter(run, client, run.workspace, run.initiated_by, directory_for(run, connection)).run_all()
            except JiraSyncStopped:
                return  # Stop sync already finished the run
            finish(run_id, "completed")
            return
        # work items per project (Jira's own count) for the progress bar and the time left
        totals = {
            project.get("key"): (project.get("insight") or {}).get("totalIssueCount") or 0
            for project in client.projects()
        }
        # projects synced before read only what changed since: their count starts at 0, not at Jira's total
        if not run.options.get("full"):
            for key in synced_before(run):
                totals[key] = 0
    except Exception as error:  # the run shows what went wrong; nothing in Jira is touched either way
        log_exception(error)
        finish(run_id, "failed", str(error))
        return
    with transaction.atomic():
        run = JiraSyncRun.objects.select_for_update().get(pk=run_id)
        run.progress = {
            key: {"status": "pending", "total": totals.get(key, 0), "done": 0, "attempts": 0}
            for key in run.project_keys
        }
        run.current_step = f"Syncing {len(run.project_keys)} projects"
        run.save(update_fields=["progress", "current_step", "updated_at"])
    for _ in range(min(LANES, len(run.project_keys)) or 1):
        jira_sync_lane_task.delay(str(run_id))


@shared_task(time_limit=60 * 60 * 6, soft_time_limit=60 * 60 * 6 - 60)
def jira_sync_lane_task(run_id):
    """Sync the next waiting project of the run, then hand over to a new task for the one after."""
    key = claim_next_project(run_id)
    if key is None:
        return
    run = JiraSyncRun.objects.select_related("workspace", "initiated_by").get(pk=run_id)
    status, error_text = "done", ""
    try:
        connection = JiraConnection.objects.get(workspace=run.workspace)
        JiraImporter(run, client_for(connection), run.workspace, run.initiated_by).sync_project(key)
    except JiraSyncStopped:
        status, error_text = "failed", "Stopped"
    except Exception as error:  # one project failing never stops the others
        log_exception(error)
        status, error_text = "failed", str(error)[:500]
    if project_finished(run_id, key, status, error_text):
        jira_sync_lane_task.delay(str(run_id))


def synced_before(run):
    """Keys of the run's projects that finished a sync before (the next sync reads only their changes)."""
    maps = {
        record.jira_key: record
        for record in JiraEntityMap.objects.filter(
            workspace=run.workspace, entity_type="project", jira_key__in=run.project_keys
        )
    }
    runs = list(
        JiraSyncRun.objects.filter(workspace=run.workspace, status__in=("completed", "failed"))
        .exclude(pk=run.pk)
        .exclude(started_at__isnull=True)
        .order_by("-started_at")[:200]
    )
    return {key for key, record in maps.items() if last_synced_at(run.workspace, key, record, runs)}


def claim_next_project(run_id):
    with transaction.atomic():
        run = JiraSyncRun.objects.select_for_update().filter(pk=run_id, status="running").first()
        if run is None:
            return None
        key = next((key for key, state in run.progress.items() if state.get("status") == "pending"), None)
        if key is None:
            return None
        now = timezone.now().isoformat()
        run.progress[key].update(
            status="running", started_at=now, heartbeat=now, attempts=run.progress[key].get("attempts", 0) + 1
        )
        run.save(update_fields=["progress", "updated_at"])
        return key


def project_finished(run_id, key, status, error_text=""):
    """Record a project's result; finish the run when nothing is left. True when more projects wait."""
    with transaction.atomic():
        run = JiraSyncRun.objects.select_for_update().get(pk=run_id)
        state = run.progress.get(key, {})
        state.update(status=status, error=error_text, finished_at=timezone.now().isoformat())
        if status == "done" and (state.get("done") or 0) < (state.get("total") or 0):
            # Jira counts work items the account cannot see (issue security): say so, never hide the gap
            run.warnings.append(
                f"{key}: {state.get('done') or 0} of {state['total']} work items could be read; Jira hides the "
                "others from the connected account."
            )
        if status == "failed":
            run.warnings.append(f"{key}: not finished ({error_text}). Sync it again to continue.")
        run.save(update_fields=["progress", "warnings", "updated_at"])
        states = [item.get("status") for item in run.progress.values()]
        if "pending" in states:
            return True
        if "running" not in states and run.status == "running":
            finish_locked(run)
        return False


def finish_locked(run, error=""):
    failed = [key for key, state in run.progress.items() if state.get("status") == "failed"]
    run.status = "failed" if error else "completed"
    run.error = (error or (f"{len(failed)} project(s) not finished: {', '.join(failed)}" if failed else ""))[:2000]
    run.current_step = "Finished"
    run.finished_at = timezone.now()
    # the uploaded users file is only needed while the run works
    run.options.pop("directory", None)
    run.save(
        update_fields=[
            "status",
            "error",
            "current_step",
            "finished_at",
            "options",
            "progress",
            "warnings",
            "updated_at",
        ]
    )


def finish(run_id, status, error=""):
    with transaction.atomic():
        run = JiraSyncRun.objects.select_for_update().get(pk=run_id)
        if status == "failed":
            finish_locked(run, error or "Failed")
        else:
            finish_locked(run)


def recover_stale_runs(workspace_id):
    """Runs interrupted by a worker restart (deploy, crash): their projects are queued again or marked failed."""
    now = timezone.now()
    for run_id in JiraSyncRun.objects.filter(
        workspace_id=workspace_id, status__in=("queued", "running"), updated_at__lt=now - STALE_AFTER
    ).values_list("id", flat=True):
        restart = False
        with transaction.atomic():
            run = JiraSyncRun.objects.select_for_update().get(pk=run_id)
            if run.updated_at >= now - STALE_AFTER:
                continue
            if run.status == "queued" or run.options.get("kind") == "users" or not run.progress:
                finish_locked(run, "Interrupted (the background worker restarted). Start the sync again.")
                continue
            for key, state in run.progress.items():
                if state.get("status") != "running":
                    continue
                if state.get("attempts", 0) >= MAX_ATTEMPTS:
                    state.update(status="failed", error="Interrupted several times")
                    run.warnings.append(f"{key}: not finished (interrupted several times). Sync it again to continue.")
                else:
                    state["status"] = "pending"  # picked up again; what was already imported is kept
                    restart = True
            states = [state.get("status") for state in run.progress.values()]
            restart = restart or "pending" in states
            if not restart and "running" not in states:
                finish_locked(run)
            else:
                run.save(update_fields=["progress", "warnings", "updated_at"])
        if restart:
            for _ in range(LANES):
                jira_sync_lane_task.delay(str(run_id))


def directory_for(run, connection):
    """Emails, status and org role of the organization's people: the uploaded users file, else the admin API."""
    if run.options.get("kind") != "users":
        return {}
    if run.options.get("directory"):
        return run.options["directory"]
    if not (connection.admin_api_key and connection.org_id):
        return {}
    run.current_step = "Reading the organization's users"
    run.save(update_fields=["current_step", "updated_at"])
    try:
        return AtlassianAdminClient(decrypt_data(connection.admin_api_key)).users(connection.org_id)
    except JiraError as error:
        run.warnings.append(f"Organization users not read ({error}); only emails Jira shows are used.")
        return {}
