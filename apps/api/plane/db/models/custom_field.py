# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class CustomField(ProjectBaseModel):
    """A field a project adds to its work items (e.g. "Task Type", "Story points"), like Jira's custom fields."""

    TYPES = (
        ("text", "Text"),
        ("textarea", "Paragraph"),
        ("number", "Number"),
        ("date", "Date"),
        ("select", "Dropdown"),
        ("multi_select", "Multi select"),
        ("checkbox", "Checkbox"),
        ("url", "URL"),
        ("user", "People"),
    )

    name = models.CharField(max_length=255)
    field_type = models.CharField(max_length=20, choices=TYPES, default="text")
    description = models.TextField(blank=True, default="")
    # choices of select / multi_select fields
    options = models.JSONField(default=list, blank=True)
    sort_order = models.FloatField(default=65535)
    # fields created by the Jira import remember the Jira field id
    external_source = models.CharField(max_length=50, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Custom Field"
        verbose_name_plural = "Custom Fields"
        db_table = "custom_fields"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"],
                condition=Q(deleted_at__isnull=True),
                name="custom_field_unique_project_name_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.name} <{self.project_id}>"


class CustomFieldValue(ProjectBaseModel):
    """The value of a custom field on a work item. ``value`` depends on the field type (string, number, list...)."""

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="custom_field_values")
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="values")
    value = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "Custom Field Value"
        verbose_name_plural = "Custom Field Values"
        db_table = "custom_field_values"
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "field"],
                condition=Q(deleted_at__isnull=True),
                name="custom_field_value_unique_issue_field_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.field_id} = {self.value!r}"
