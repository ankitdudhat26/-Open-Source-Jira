# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project custom fields: validation of values per type, display text and the history entry of a change."""

from datetime import date

from django.utils import timezone

from plane.db.models import CustomField, CustomFieldValue, IssueActivity, ProjectMember, User
from plane.utils.uuid import is_valid_uuid

FIELD_TYPES = {key for key, _ in CustomField.TYPES}


class CustomFieldError(Exception):
    pass


def clean_options(options):
    if options is None:
        return []
    if not isinstance(options, list):
        raise CustomFieldError("options must be a list of names.")
    cleaned = []
    for option in options:
        name = str(option or "").strip()[:255]
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def clean_value(field, value):
    """The value to store for ``field`` (None clears it). Raises CustomFieldError when it does not fit the type."""
    if value is None or value == "" or value == []:
        return None
    kind = field.field_type
    if kind in ("text", "url"):
        text = str(value).strip()
        if kind == "url" and not text.startswith(("http://", "https://")):
            raise CustomFieldError("Enter a link starting with http:// or https://")
        return text[:2000] or None
    if kind == "textarea":
        return str(value).strip()[:20000] or None
    if kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise CustomFieldError(f"{field.name} must be a number.")
        return int(number) if number.is_integer() else number
    if kind == "date":
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            raise CustomFieldError(f"{field.name} must be a date (YYYY-MM-DD).")
    if kind == "checkbox":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes")
    if kind == "select":
        choice = str(value)
        if choice not in field.options:
            raise CustomFieldError(f"'{choice}' is not an option of {field.name}.")
        return choice
    if kind == "multi_select":
        if not isinstance(value, list):
            raise CustomFieldError(f"{field.name} takes a list of options.")
        choices = [str(item) for item in value]
        unknown = [choice for choice in choices if choice not in field.options]
        if unknown:
            raise CustomFieldError(f"Not options of {field.name}: {', '.join(unknown)}.")
        return list(dict.fromkeys(choices)) or None
    if kind == "user":
        ids = value if isinstance(value, list) else [value]
        ids = [str(item) for item in ids if item]
        if not all(is_valid_uuid(item) for item in ids):
            raise CustomFieldError("People must be given by user id.")
        members = {
            str(member_id)
            for member_id in ProjectMember.objects.filter(
                project_id=field.project_id, member_id__in=ids, is_active=True
            ).values_list("member_id", flat=True)
        }
        if set(ids) - members:
            raise CustomFieldError("Only members of this project can be chosen.")
        return list(dict.fromkeys(ids)) or None
    raise CustomFieldError("Unknown field type.")


def display_value(field, value):
    """Short text of a value, for history entries."""
    if value is None or value == [] or value == "":
        return ""
    if field.field_type == "checkbox":
        return "Yes" if value else "No"
    if field.field_type == "user":
        names = dict(User.objects.filter(pk__in=value).values_list("id", "display_name"))
        return ", ".join(names.get(user_id, "") or "Unknown" for user_id in [*map(str, value)] if user_id) or ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    text = str(value)
    return text if len(text) <= 200 else f"{text[:197]}..."


def serialize_field(field):
    return {
        "id": str(field.id),
        "project": str(field.project_id),
        "name": field.name,
        "field_type": field.field_type,
        "description": field.description,
        "options": field.options,
        "sort_order": field.sort_order,
        "external_source": field.external_source,
    }


def set_value(issue, field, value, actor, log=True):
    """Store (or clear) the value and add a history entry when it changed. Returns the stored value."""
    cleaned = clean_value(field, value)
    record = CustomFieldValue.objects.filter(issue=issue, field=field).first()
    old = record.value if record else None
    if old == cleaned:
        return cleaned
    if cleaned is None:
        if record:
            record.delete(soft=False)
    elif record:
        record.value = cleaned
        record.save(update_fields=["value", "updated_at"])
    else:
        CustomFieldValue.objects.create(
            issue=issue, field=field, value=cleaned, project_id=issue.project_id, workspace_id=issue.workspace_id
        )
    if log:
        IssueActivity.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=actor,
            verb="updated",
            field="custom_field",
            old_value=display_value(field, old)[:5000],
            new_value=display_value(field, cleaned)[:5000],
            external_field_name=field.name,
            comment=f"updated {field.name}",
            epoch=int(timezone.now().timestamp()),
        )
    return cleaned
