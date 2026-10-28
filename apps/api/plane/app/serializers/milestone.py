# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from .base import BaseSerializer
from plane.db.models import Deliverable, Milestone, Module, Project, ProjectResource, User
from plane.utils.project_membership import is_workspace_assignable


class MilestoneSerializer(BaseSerializer):
    module_ids = serializers.ListField(child=serializers.UUIDField(), required=False, write_only=True)

    class Meta:
        model = Milestone
        fields = [
            "id",
            "code",
            "name",
            "amount",
            "payment_percentage",
            "description",
            "sort_order",
            "module_ids",
            "project",
            "workspace",
            "external_source",
            "external_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["project", "workspace", "external_source", "external_id", "created_at", "updated_at"]

    def validate_module_ids(self, value):
        project_id = self.context.get("project_id")
        valid = set(Module.objects.filter(project_id=project_id, id__in=value).values_list("id", flat=True))
        invalid = [str(module_id) for module_id in value if module_id not in valid]
        if invalid:
            raise serializers.ValidationError(f"Modules do not belong to this project: {', '.join(invalid)}")
        return value


class DeliverableSerializer(BaseSerializer):
    milestone_id = serializers.PrimaryKeyRelatedField(
        source="milestone", queryset=Milestone.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Deliverable
        fields = [
            "id",
            "code",
            "name",
            "description",
            "milestone_id",
            "sort_order",
            "project",
            "workspace",
            "external_source",
            "external_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["project", "workspace", "external_source", "external_id", "created_at", "updated_at"]

    def validate(self, attrs):
        milestone = attrs.get("milestone")
        if milestone is not None and str(milestone.project_id) != str(self.context.get("project_id")):
            raise serializers.ValidationError({"milestone_id": "Milestone does not belong to this project"})
        return attrs


class ProjectResourceSerializer(BaseSerializer):
    member_id = serializers.PrimaryKeyRelatedField(
        source="member", queryset=User.objects.all(), required=False, allow_null=True
    )
    label_id = serializers.PrimaryKeyRelatedField(source="label", read_only=True)

    class Meta:
        model = ProjectResource
        fields = [
            "id",
            "code",
            "role",
            "resource_type",
            "responsibilities",
            "member_id",
            "label_id",
            "sort_order",
            "project",
            "workspace",
            "external_source",
            "external_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "label_id",
            "project",
            "workspace",
            "external_source",
            "external_id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        member = attrs.get("member")
        if member is not None:
            workspace_id = (
                Project.objects.filter(pk=self.context.get("project_id")).values_list("workspace_id", flat=True).first()
            )
            # the member joins the project when mapped (see ProjectResourceEndpoint)
            if not is_workspace_assignable(workspace_id, member.id):
                raise serializers.ValidationError(
                    {"member_id": "Only members and admins of the workspace can be mapped"}
                )
        if "role" in attrs and not attrs["role"].strip():
            raise serializers.ValidationError({"role": "Role is required"})
        return attrs
