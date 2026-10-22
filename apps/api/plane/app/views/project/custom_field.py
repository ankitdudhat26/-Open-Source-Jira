# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError
from django.db.models import Max

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import CustomField, CustomFieldValue, Issue
from plane.utils.custom_fields import (
    FIELD_TYPES,
    CustomFieldError,
    clean_options,
    serialize_field,
    set_value,
)


def error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"error": str(message)}, status=code)


class ProjectCustomFieldEndpoint(BaseAPIView):
    """The custom fields of a project. Everyone in the project sees them; admins manage them."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        fields = CustomField.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response([serialize_field(field) for field in fields], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        name = str(request.data.get("name") or "").strip()[:255]
        field_type = request.data.get("field_type") or "text"
        if not name:
            return error("Field name is required.")
        if field_type not in FIELD_TYPES:
            return error("Unknown field type.")
        try:
            options = clean_options(request.data.get("options"))
        except CustomFieldError as exc:
            return error(exc)
        if field_type in ("select", "multi_select") and not options:
            return error("Add at least one option.")
        if CustomField.objects.filter(project_id=project_id, name__iexact=name).exists():
            return error("A field with this name already exists in the project.")
        last = CustomField.objects.filter(project_id=project_id).aggregate(last=Max("sort_order"))["last"] or 0
        try:
            field = CustomField.objects.create(
                project_id=project_id,
                name=name,
                field_type=field_type,
                description=str(request.data.get("description") or ""),
                options=options,
                sort_order=last + 10000,
            )
        except IntegrityError:
            return error("A field with this name already exists in the project.")
        return Response(serialize_field(field), status=status.HTTP_201_CREATED)


class ProjectCustomFieldDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, field_id):
        field = CustomField.objects.filter(workspace__slug=slug, project_id=project_id, pk=field_id).first()
        if field is None:
            return error("Field not found.", status.HTTP_404_NOT_FOUND)
        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()[:255]
            if not name:
                return error("Field name is required.")
            if CustomField.objects.filter(project_id=project_id, name__iexact=name).exclude(pk=field.pk).exists():
                return error("A field with this name already exists in the project.")
            field.name = name
        if "description" in request.data:
            field.description = str(request.data.get("description") or "")
        if "options" in request.data:
            try:
                field.options = clean_options(request.data.get("options"))
            except CustomFieldError as exc:
                return error(exc)
        if "field_type" in request.data and request.data["field_type"] != field.field_type:
            if request.data["field_type"] not in FIELD_TYPES:
                return error("Unknown field type.")
            if CustomFieldValue.objects.filter(field=field).exists():
                return error("The type cannot change once work items have a value. Create a new field instead.")
            field.field_type = request.data["field_type"]
        if field.field_type in ("select", "multi_select") and not field.options:
            return error("Add at least one option.")
        if "sort_order" in request.data:
            try:
                field.sort_order = float(request.data["sort_order"])
            except (TypeError, ValueError):
                return error("sort_order must be a number.")
        try:
            field.save()
        except IntegrityError:
            return error("A field with this name already exists in the project.")
        return Response(serialize_field(field), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, field_id):
        field = CustomField.objects.filter(workspace__slug=slug, project_id=project_id, pk=field_id).first()
        if field is None:
            return error("Field not found.", status.HTTP_404_NOT_FOUND)
        CustomFieldValue.objects.filter(field=field).delete(soft=False)
        field.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssueCustomFieldValuesEndpoint(BaseAPIView):
    """Values of the project's custom fields on one work item."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        values = CustomFieldValue.objects.filter(workspace__slug=slug, project_id=project_id, issue_id=issue_id).values(
            "field_id", "value"
        )
        return Response(
            {str(item["field_id"]): item["value"] for item in values},
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        issue = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
        if issue is None:
            return error("Work item not found.", status.HTTP_404_NOT_FOUND)
        field = CustomField.objects.filter(project_id=project_id, pk=request.data.get("field_id")).first()
        if field is None:
            return error("Field not found.", status.HTTP_404_NOT_FOUND)
        try:
            value = set_value(issue, field, request.data.get("value"), request.user)
        except CustomFieldError as exc:
            return error(exc)
        return Response({"field_id": str(field.id), "value": value}, status=status.HTTP_200_OK)
