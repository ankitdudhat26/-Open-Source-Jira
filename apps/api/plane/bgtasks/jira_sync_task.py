# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import logging

from celery import shared_task
from django.utils import timezone

from plane.db.models import JiraConnection, JiraSyncRun
from plane.license.utils.encryption import decrypt_data
from plane.utils.exception_logger import log_exception
from plane.utils.jira.client import JiraClient
from plane.utils.jira.importer import JiraImporter

logger = logging.getLogger("plane.worker")


@shared_task(time_limit=60 * 60 * 6, soft_time_limit=60 * 60 * 6 - 60)
def jira_sync_task(run_id):
    """Import / sync the selected Jira projects of a sync run (Jira is only read)."""
    run = JiraSyncRun.objects.filter(pk=run_id).select_related("workspace", "initiated_by").first()
    if run is None or run.status not in ("queued", "running"):
        return
    run.status = "running"
    run.started_at = timezone.now()
    run.current_step = "Connecting to Jira"
    run.save(update_fields=["status", "started_at", "current_step", "updated_at"])
    try:
        connection = JiraConnection.objects.get(workspace=run.workspace)
        client = JiraClient(connection.site_url, connection.email, decrypt_data(connection.api_token))
        JiraImporter(run, client, run.workspace, run.initiated_by).run_all()
        run.status = "completed"
    except Exception as error:  # the run shows what went wrong; nothing in Jira is touched either way
        log_exception(error)
        run.status = "failed"
        run.error = str(error)[:2000]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at", "updated_at"])
