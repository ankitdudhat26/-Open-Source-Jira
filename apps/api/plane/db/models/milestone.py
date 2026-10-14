# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class Milestone(ProjectBaseModel):
    """A billing milestone of a project (e.g. "Design Signoff"), delivered through the modules linked to it."""

    # Milestone ID from the SOW (e.g. "M1"), empty for manually added milestones
    code = models.CharField(max_length=50, blank=True, default="")
    name = models.CharField(max_length=255, verbose_name="Milestone Name")
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    payment_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # Scope / acceptance criteria
    description = models.TextField(blank=True, default="")
    modules = models.ManyToManyField(
        "db.Module",
        blank=True,
        related_name="milestones",
        through="MilestoneModule",
        through_fields=("milestone", "module"),
    )
    sort_order = models.FloatField(default=65535)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Milestone"
        verbose_name_plural = "Milestones"
        db_table = "milestones"
        ordering = ("sort_order", "created_at")

    def save(self, *args, **kwargs):
        if self._state.adding and self.sort_order == 65535:
            largest = Milestone.objects.filter(project_id=self.project_id).aggregate(largest=models.Max("sort_order"))[
                "largest"
            ]
            if largest is not None:
                self.sort_order = largest + 10000
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} {self.name}"


class MilestoneModule(ProjectBaseModel):
    milestone = models.ForeignKey("db.Milestone", on_delete=models.CASCADE, related_name="milestone_modules")
    module = models.ForeignKey("db.Module", on_delete=models.CASCADE, related_name="module_milestones")

    class Meta:
        unique_together = ["milestone", "module", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["milestone", "module"],
                condition=Q(deleted_at__isnull=True),
                name="milestone_module_unique_milestone_module_when_deleted_at_null",
            )
        ]
        verbose_name = "Milestone Module"
        verbose_name_plural = "Milestone Modules"
        db_table = "milestone_modules"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.milestone.name} {self.module.name}"


class Deliverable(ProjectBaseModel):
    """A deliverable promised to the client, handed over at a milestone."""

    # Deliverable ID from the SOW (e.g. "D01"), empty for manually added deliverables
    code = models.CharField(max_length=50, blank=True, default="")
    name = models.CharField(max_length=255, verbose_name="Deliverable Name")
    description = models.TextField(blank=True, default="")
    milestone = models.ForeignKey(
        "db.Milestone",
        on_delete=models.SET_NULL,
        related_name="deliverables",
        null=True,
        blank=True,
    )
    sort_order = models.FloatField(default=65535)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Deliverable"
        verbose_name_plural = "Deliverables"
        db_table = "deliverables"
        ordering = ("sort_order", "created_at")

    def save(self, *args, **kwargs):
        if self._state.adding and self.sort_order == 65535:
            largest = Deliverable.objects.filter(project_id=self.project_id).aggregate(
                largest=models.Max("sort_order")
            )["largest"]
            if largest is not None:
                self.sort_order = largest + 10000
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} {self.name}"


class ProjectResource(ProjectBaseModel):
    """A role from the SOW (e.g. "R03 Full Stack Developer 1") mapped to the project member who fills it.

    Tasks of a resource carry its label; mapping a member assigns those tasks to them.
    """

    # Resource ID from the SOW (e.g. "R03"), empty for manually added resources
    code = models.CharField(max_length=50, blank=True, default="")
    role = models.CharField(max_length=255)
    resource_type = models.CharField(max_length=255, blank=True, default="")
    responsibilities = models.TextField(blank=True, default="")
    member = models.ForeignKey(
        "db.User",
        on_delete=models.SET_NULL,
        related_name="project_resources",
        null=True,
        blank=True,
    )
    label = models.ForeignKey(
        "db.Label",
        on_delete=models.SET_NULL,
        related_name="project_resources",
        null=True,
        blank=True,
    )
    sort_order = models.FloatField(default=65535)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Project Resource"
        verbose_name_plural = "Project Resources"
        db_table = "project_resources"
        ordering = ("sort_order", "created_at")

    def save(self, *args, **kwargs):
        if self._state.adding and self.sort_order == 65535:
            largest = ProjectResource.objects.filter(project_id=self.project_id).aggregate(
                largest=models.Max("sort_order")
            )["largest"]
            if largest is not None:
                self.sort_order = largest + 10000
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} {self.role}".strip()
