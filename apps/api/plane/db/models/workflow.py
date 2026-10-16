# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class ProjectWorkflow(ProjectBaseModel):
    """Jira style workflow of a project: whether the state transition rules below are enforced."""

    is_enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Project Workflow"
        verbose_name_plural = "Project Workflows"
        db_table = "project_workflows"
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=Q(deleted_at__isnull=True),
                name="project_workflow_unique_project_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.project_id} workflow ({'on' if self.is_enabled else 'off'})"


class WorkflowTransition(ProjectBaseModel):
    """A permitted state change: work items in ``from_state`` can move to ``to_state``.

    A state without any transition is not restricted. ``reviewer_ids`` limits who can make the change
    (project admins always can); empty means every member.
    """

    from_state = models.ForeignKey("db.State", on_delete=models.CASCADE, related_name="outgoing_transitions")
    to_state = models.ForeignKey("db.State", on_delete=models.CASCADE, related_name="incoming_transitions")
    reviewer_ids = ArrayField(models.UUIDField(), blank=True, default=list)

    class Meta:
        verbose_name = "Workflow Transition"
        verbose_name_plural = "Workflow Transitions"
        db_table = "workflow_transitions"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["from_state", "to_state"],
                condition=Q(deleted_at__isnull=True),
                name="workflow_transition_unique_from_to_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.from_state_id} -> {self.to_state_id}"
