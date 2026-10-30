# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The request form of a project's Intake: which fields it shows, who is invited to it (clients log in on its link),
and the requests they sent with their status."""

from django.db.models import Q

from plane.db.models import IntakeForm, IntakeFormInvite, IntakeIssue, Label, Project, ProjectIssueType, ProjectMember

# the fields of a request, in form order — every one is on until a project admin turns it off; the title is always on
FORM_FIELDS = [
    {"key": "title", "label": "Title", "locked": True},
    {"key": "description", "label": "Description"},
    {"key": "type", "label": "Type"},
    {"key": "priority", "label": "Priority"},
    {"key": "labels", "label": "Labels"},
    {"key": "attachments", "label": "Attachments"},
]
FIELD_KEYS = {field["key"] for field in FORM_FIELDS}
# the work item data each field sets — dropped from a request when the field is off
ISSUE_DATA_KEYS = {
    "description": ("description_html", "description_json", "description_binary"),
    "type": ("type_id",),
    "priority": ("priority",),
    "labels": ("label_ids", "labels"),
}
PRIORITIES = [
    {"value": "urgent", "label": "Urgent"},
    {"value": "high", "label": "High"},
    {"value": "medium", "label": "Medium"},
    {"value": "low", "label": "Low"},
    {"value": "none", "label": "None"},
]
# the Client role of a project (a guest): views its work items and sends requests on its form
CLIENT_ROLE = 5
STATUS_LABELS = {-2: "Pending", -1: "Declined", 0: "Snoozed", 1: "Accepted", 2: "Duplicate"}


class IntakeFormError(Exception):
    pass


def get_form(project):
    """The project's form, created on first use (link off, every field on)."""
    return IntakeForm.objects.filter(project=project).first() or IntakeForm.objects.create(project=project)


def form_fields(project_id):
    """Every field of the project's form with whether it is shown."""
    form = IntakeForm.objects.filter(project_id=project_id).first()
    config = (form.fields if form else None) or {}
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "visible": True if field.get("locked") else bool(config.get(field["key"], {}).get("visible", True)),
            "locked": bool(field.get("locked")),
        }
        for field in FORM_FIELDS
    ]


def visible_fields(project_id):
    return {field["key"] for field in form_fields(project_id) if field["visible"]}


def save_form_fields(form, config):
    """Store which fields are on. ``config`` is {"<key>": {"visible": bool}}; unknown keys and the title are ignored."""
    if not isinstance(config, dict):
        raise IntakeFormError("fields must be an object of field keys.")
    fields = dict(form.fields or {})
    for key, value in config.items():
        if key in FIELD_KEYS and key != "title" and isinstance(value, dict) and "visible" in value:
            fields[key] = {"visible": bool(value["visible"])}
    form.fields = fields


def strip_hidden_fields(project_id, issue_data):
    """The work item data of a request without what the turned-off fields would set."""
    shown = visible_fields(project_id)
    hidden_keys = {key for field, keys in ISSUE_DATA_KEYS.items() if field not in shown for key in keys}
    return {key: value for key, value in issue_data.items() if key not in hidden_keys}


def project_form(project):
    """A project's form as the request page draws it: the shown fields and their choices."""
    shown = visible_fields(project.id)
    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "project_identifier": project.identifier,
        "fields": [field["key"] for field in FORM_FIELDS if field["key"] in shown],
        "types": [
            {"id": str(type_id), "name": name, "color": type_color(logo_props)}
            for type_id, name, logo_props in ProjectIssueType.objects.filter(
                project=project, issue_type__is_active=True, issue_type__deleted_at__isnull=True
            )
            .order_by("level", "issue_type__name")
            .values_list("issue_type_id", "issue_type__name", "issue_type__logo_props")
        ]
        if "type" in shown
        else [],
        "priorities": PRIORITIES if "priority" in shown else [],
        "labels": [
            {"id": str(label_id), "name": name, "color": color}
            for label_id, name, color in Label.objects.filter(project=project)
            .order_by("sort_order", "name")
            .values_list("id", "name", "color")
        ]
        if "labels" in shown
        else [],
    }


def type_color(logo_props):
    return ((logo_props or {}).get("icon") or {}).get("color") or "#6B7280"


def open_form_filter():
    """Projects whose request form takes requests: Intake on, link on, not archived."""
    return Q(
        intake_view=True,
        archived_at__isnull=True,
        project_intakeform__is_enabled=True,
        project_intakeform__deleted_at__isnull=True,
    )


def _client_access(user):
    """Invited to the form by their email, or a client (guest) of the project — both send requests on its link."""
    return Q(
        project_intakeforminvite__email__iexact=user.email,
        project_intakeforminvite__deleted_at__isnull=True,
    ) | Q(
        project_projectmember__member=user,
        project_projectmember__is_active=True,
        project_projectmember__role=CLIENT_ROLE,
        project_projectmember__deleted_at__isnull=True,
    )


def invited_projects(user):
    """The projects whose request form the user can use (invited, or a client of the project) that take requests."""
    return (
        Project.objects.filter(open_form_filter())
        .filter(_client_access(user))
        .select_related("workspace")
        .distinct()
        .order_by("name")
    )


def is_invited(user, project_id):
    return (
        IntakeFormInvite.objects.filter(project_id=project_id, email__iexact=user.email).exists()
        or ProjectMember.objects.filter(project_id=project_id, member=user, is_active=True, role=CLIENT_ROLE).exists()
    )


def decline_reason(intake_issue):
    return (intake_issue.extra or {}).get("decline_reason", "")


def user_requests(user, project_ids):
    """The requests the user sent to the given projects, newest first, with their status and the decline reason."""
    requests = (
        IntakeIssue.objects.filter(created_by=user, project_id__in=project_ids, issue__deleted_at__isnull=True)
        .select_related("issue", "issue__type", "project", "duplicate_to")
        .prefetch_related("issue__labels")
        .order_by("-created_at")
    )
    return [
        {
            "id": str(request.id),
            "issue_id": str(request.issue_id),
            "project_id": str(request.project_id),
            "project_name": request.project.name,
            "key": f"{request.project.identifier}-{request.issue.sequence_id}",
            "name": request.issue.name,
            "priority": request.issue.priority,
            "type": (
                {"name": request.issue.type.name, "color": type_color(request.issue.type.logo_props)}
                if request.issue.type
                else None
            ),
            "labels": [{"name": label.name, "color": label.color} for label in request.issue.labels.all()],
            "status": request.status,
            "status_label": STATUS_LABELS.get(request.status, ""),
            "decline_reason": decline_reason(request),
            "duplicate_of": (
                f"{request.project.identifier}-{request.duplicate_to.sequence_id}" if request.duplicate_to else None
            ),
            "snoozed_till": request.snoozed_till,
            "created_at": request.created_at,
            "updated_at": request.updated_at,
        }
        for request in requests
    ]
