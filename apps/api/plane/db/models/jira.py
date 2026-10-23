# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

# Module imports
from .base import BaseModel


class JiraConnection(BaseModel):
    """Read only Jira Cloud credentials of a workspace (the API token is stored encrypted)."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="jira_connections")
    site_url = models.URLField(max_length=500)
    email = models.EmailField(max_length=255)
    api_token = models.TextField()
    account_name = models.CharField(max_length=255, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    # optional Atlassian organization admin API key (encrypted): the only read only way to the people's emails
    admin_api_key = models.TextField(blank=True, default="")
    org_id = models.CharField(max_length=255, blank=True, default="")
    org_name = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Jira Connection"
        verbose_name_plural = "Jira Connections"
        db_table = "jira_connections"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=Q(deleted_at__isnull=True),
                name="jira_connection_unique_workspace_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.site_url} <{self.workspace_id}>"


class JiraSyncRun(BaseModel):
    """One import / sync of Jira projects into the workspace."""

    STATUS_CHOICES = (
        ("queued", "Queued"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="jira_sync_runs")
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="jira_sync_runs"
    )
    project_keys = ArrayField(models.CharField(max_length=50), default=list)
    options = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    current_step = models.CharField(max_length=255, blank=True, default="")
    stats = models.JSONField(default=dict)
    # project key -> {"project_id": ..., "name": ...}
    projects = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    unmatched_users = models.JSONField(default=list)
    error = models.TextField(blank=True, default="")
    # project key -> {status: pending|running|done|failed, total, done, attempts, heartbeat, error, ...}
    progress = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Jira Sync Run"
        verbose_name_plural = "Jira Sync Runs"
        db_table = "jira_sync_runs"
        ordering = ("-created_at",)

    def __str__(self):
        return f"Jira sync {self.project_keys} ({self.status})"


class JiraEntityMap(BaseModel):
    """Which Jira object became which object here, so syncing again updates instead of duplicating."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="jira_entity_maps")
    # project, status, issue, comment, history, sprint, component, attachment, link
    entity_type = models.CharField(max_length=30)
    jira_id = models.CharField(max_length=255)
    plane_id = models.UUIDField(null=True, blank=True)
    # e.g. the Jira key "SHOP-12" or the parent project key
    jira_key = models.CharField(max_length=255, blank=True, default="")
    jira_updated = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "Jira Entity Map"
        verbose_name_plural = "Jira Entity Maps"
        db_table = "jira_entity_maps"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "entity_type", "jira_id"],
                condition=Q(deleted_at__isnull=True),
                name="jira_entity_map_unique_when_deleted_at_null",
            )
        ]
        indexes = [models.Index(fields=["workspace", "entity_type", "plane_id"])]

    def __str__(self):
        return f"{self.entity_type} {self.jira_id} -> {self.plane_id}"
