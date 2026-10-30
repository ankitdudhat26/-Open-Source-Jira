# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from uuid import uuid4

# Django imports
from django.db import models

# Module imports
from plane.db.models.project import ProjectBaseModel


class Intake(ProjectBaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(verbose_name="Intake Description", blank=True)
    is_default = models.BooleanField(default=False)
    view_props = models.JSONField(default=dict)
    logo_props = models.JSONField(default=dict)

    def __str__(self):
        """Return name of the intake"""
        return f"{self.name} <{self.project.name}>"

    class Meta:
        unique_together = ["name", "project", "deleted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "project"],
                condition=models.Q(deleted_at__isnull=True),
                name="intake_unique_name_project_when_deleted_at_null",
            )
        ]
        verbose_name = "Intake"
        verbose_name_plural = "Intakes"
        db_table = "intakes"
        ordering = ("name",)


class SourceType(models.TextChoices):
    IN_APP = "IN_APP"


class IntakeIssueStatus(models.IntegerChoices):
    PENDING = -2
    REJECTED = -1
    SNOOZED = 0
    ACCEPTED = 1
    DUPLICATE = 2


class IntakeIssue(ProjectBaseModel):
    intake = models.ForeignKey("db.Intake", related_name="issue_intake", on_delete=models.CASCADE)
    issue = models.ForeignKey("db.Issue", related_name="issue_intake", on_delete=models.CASCADE)
    status = models.IntegerField(
        choices=(
            (-2, "Pending"),
            (-1, "Rejected"),
            (0, "Snoozed"),
            (1, "Accepted"),
            (2, "Duplicate"),
        ),
        default=-2,
    )
    snoozed_till = models.DateTimeField(null=True)
    duplicate_to = models.ForeignKey(
        "db.Issue",
        related_name="intake_duplicate",
        on_delete=models.SET_NULL,
        null=True,
    )
    source = models.CharField(max_length=255, default="IN_APP", null=True, blank=True)
    source_email = models.TextField(blank=True, null=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True, null=True)
    extra = models.JSONField(default=dict)

    class Meta:
        verbose_name = "IntakeIssue"
        verbose_name_plural = "IntakeIssues"
        db_table = "intake_issues"
        ordering = ("-created_at",)

    def __str__(self):
        """Return name of the Issue"""
        return f"{self.issue.name} <{self.intake.name}>"


def get_form_anchor():
    return uuid4().hex


class IntakeForm(ProjectBaseModel):
    """The request form of a project's Intake, opened from its link. Only the people invited to it (see
    IntakeFormInvite) can log in there, send requests and follow their status. ``fields`` says which fields the form
    shows — every one until a project admin turns it off (see plane.utils.intake_form for the keys)."""

    anchor = models.CharField(max_length=64, default=get_form_anchor, unique=True, db_index=True)
    is_enabled = models.BooleanField(default=False)
    # {"<field key>": {"visible": bool}}
    fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Intake Form"
        verbose_name_plural = "Intake Forms"
        db_table = "intake_forms"
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="intake_form_unique_project_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"Intake form <{self.project_id}>"


class IntakeFormInvite(ProjectBaseModel):
    """A person (a client) invited to a project's Intake form. They log in on the form's link with this email and can
    only send requests there and follow them — they are not members of the project."""

    email = models.EmailField()
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Intake Form Invite"
        verbose_name_plural = "Intake Form Invites"
        db_table = "intake_form_invites"
        ordering = ("email",)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "email"],
                condition=models.Q(deleted_at__isnull=True),
                name="intake_form_invite_unique_project_email_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.email} <{self.project_id}>"
