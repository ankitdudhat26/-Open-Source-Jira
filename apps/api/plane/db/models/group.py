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
from .project import ProjectBaseModel


class WorkspaceGroup(BaseModel):
    """A group of people across projects (e.g. "DevOps") with its own rights and, optionally, a queue (Q).

    ``permissions`` holds rights keys from ``plane.utils.groups.GROUP_PERMISSIONS``; new rights can be added there
    without changing the data model.
    """

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="workspace_groups")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    color = models.CharField(max_length=32, blank=True, default="#2563EB")
    has_queue = models.BooleanField(default=True)
    permissions = ArrayField(models.CharField(max_length=64), blank=True, default=list)
    # created by the system (e.g. DevOps); can be edited like any other group
    is_default = models.BooleanField(default=False)
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Workspace Group"
        verbose_name_plural = "Workspace Groups"
        db_table = "workspace_groups"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=Q(deleted_at__isnull=True),
                name="workspace_group_unique_name_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.name} <{self.workspace_id}>"


class WorkspaceGroupMember(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="workspace_group_members")
    group = models.ForeignKey(WorkspaceGroup, on_delete=models.CASCADE, related_name="group_members")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_groups")

    class Meta:
        verbose_name = "Workspace Group Member"
        verbose_name_plural = "Workspace Group Members"
        db_table = "workspace_group_members"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["group", "member"],
                condition=Q(deleted_at__isnull=True),
                name="workspace_group_member_unique_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.member_id} in {self.group_id}"


class QueueItem(ProjectBaseModel):
    """A work item waiting in (or handled through) a group's queue. A work item is in at most one queue."""

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="queue_items")
    group = models.ForeignKey(WorkspaceGroup, on_delete=models.CASCADE, related_name="queue_items")
    note = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Queue Item"
        verbose_name_plural = "Queue Items"
        db_table = "queue_items"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["issue"],
                condition=Q(deleted_at__isnull=True),
                name="queue_item_unique_issue_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.issue_id} in queue {self.group_id}"
