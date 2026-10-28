# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.db import transaction
from django.db.models import Count, Q

# Third party imports
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers.milestone import DeliverableSerializer, MilestoneSerializer, ProjectResourceSerializer
from plane.app.views.base import BaseAPIView
from plane.db.models import (
    Deliverable,
    Issue,
    IssueLabel,
    Milestone,
    MilestoneModule,
    Project,
    ProjectResource,
)
from plane.utils.grouper import issue_queryset_grouper
from plane.utils.host import base_host
from plane.utils.project_membership import add_members_to_project
from plane.utils.project_resources import sync_resource_assignees
from plane.utils.sow_import import GROUP_COLORS, RESOURCE_GROUP, ensure_label
from plane.utils.sow_import import build_summary, import_sow
from plane.utils.sow_parser import SOWParseError, parse_sow
from plane.utils.work_item_types import ensure_project_work_item_types, serialize_work_item_types

# 10 MB is plenty for a SOW workbook
MAX_SOW_FILE_SIZE = 10 * 1024 * 1024

DONE_STATE_GROUPS = ["completed", "cancelled"]


def set_milestone_modules(milestone, module_ids):
    """Replace the modules linked to a milestone."""
    module_ids = {str(module_id) for module_id in module_ids}
    existing = {str(link.module_id): link for link in MilestoneModule.objects.filter(milestone=milestone)}
    for module_id, link in existing.items():
        if module_id not in module_ids:
            link.delete(soft=False)
    MilestoneModule.objects.bulk_create(
        [
            MilestoneModule(
                milestone=milestone,
                module_id=module_id,
                project_id=milestone.project_id,
                workspace_id=milestone.workspace_id,
            )
            for module_id in module_ids
            if module_id not in existing
        ]
    )


def milestone_progress(milestone, module_ids):
    """Work items that make up a milestone.

    A milestone covers the work items tagged with it plus the untagged work items of the modules linked to it,
    so manually planned projects (modules only) and SOW imports (every feature/task tagged) both work.
    The milestone is complete once all of those work items are completed or cancelled.
    """
    scope = Q(milestone_id=milestone.id)
    if module_ids:
        scope |= Q(
            milestone__isnull=True,
            issue_module__module_id__in=module_ids,
            issue_module__deleted_at__isnull=True,
        )
    issues = Issue.issue_objects.filter(project_id=milestone.project_id).filter(scope)

    totals = issues.aggregate(
        total=Count("id", distinct=True),
        completed=Count("id", distinct=True, filter=Q(state__group="completed")),
        cancelled=Count("id", distinct=True, filter=Q(state__group="cancelled")),
    )

    module_rows = (
        issues.filter(issue_module__module_id__in=module_ids, issue_module__deleted_at__isnull=True)
        .values("issue_module__module_id")
        .annotate(
            total=Count("id", distinct=True),
            done=Count("id", distinct=True, filter=Q(state__group__in=DONE_STATE_GROUPS)),
        )
    )
    module_progress = {str(row["issue_module__module_id"]): row for row in module_rows}

    done = totals["completed"] + totals["cancelled"]
    return {
        "total_issues": totals["total"],
        "completed_issues": totals["completed"],
        "cancelled_issues": totals["cancelled"],
        "is_completed": totals["total"] > 0 and done == totals["total"],
        "modules": [
            {
                "module_id": module_id,
                "total_issues": module_progress.get(module_id, {}).get("total", 0),
                "done_issues": module_progress.get(module_id, {}).get("done", 0),
                "is_completed": module_progress.get(module_id, {}).get("total", 0) > 0
                and module_progress[module_id]["done"] == module_progress[module_id]["total"],
            }
            for module_id in module_ids
        ],
    }


def serialize_milestone(milestone):
    module_ids = [
        str(module_id)
        for module_id in MilestoneModule.objects.filter(
            milestone=milestone, module__archived_at__isnull=True, module__deleted_at__isnull=True
        )
        .order_by("module__created_at")
        .values_list("module_id", flat=True)
    ]
    return {
        **MilestoneSerializer(milestone).data,
        "module_ids": module_ids,
        **milestone_progress(milestone, module_ids),
    }


class MilestoneEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, pk=None):
        milestones = Milestone.objects.filter(workspace__slug=slug, project_id=project_id)
        if pk:
            return Response(serialize_milestone(milestones.get(pk=pk)), status=status.HTTP_200_OK)
        return Response([serialize_milestone(milestone) for milestone in milestones], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        serializer = MilestoneSerializer(data=request.data, context={"project_id": project_id})
        serializer.is_valid(raise_exception=True)
        module_ids = serializer.validated_data.pop("module_ids", None)
        with transaction.atomic():
            milestone = serializer.save(project_id=project_id)
            if module_ids is not None:
                set_milestone_modules(milestone, module_ids)
        return Response(serialize_milestone(milestone), status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        milestone = Milestone.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        serializer = MilestoneSerializer(
            milestone, data=request.data, partial=True, context={"project_id": project_id}
        )
        serializer.is_valid(raise_exception=True)
        module_ids = serializer.validated_data.pop("module_ids", None)
        with transaction.atomic():
            milestone = serializer.save()
            if module_ids is not None:
                set_milestone_modules(milestone, module_ids)
        return Response(serialize_milestone(milestone), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        milestone = Milestone.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        with transaction.atomic():
            # Keep the deliverables and work items, just unlink them
            Deliverable.objects.filter(milestone=milestone).update(milestone=None)
            Issue.all_objects.filter(milestone=milestone).update(milestone=None)
            MilestoneModule.objects.filter(milestone=milestone).delete(soft=False)
            milestone.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeliverableEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        deliverables = Deliverable.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response(DeliverableSerializer(deliverables, many=True).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        serializer = DeliverableSerializer(data=request.data, context={"project_id": project_id})
        serializer.is_valid(raise_exception=True)
        serializer.save(project_id=project_id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        deliverable = Deliverable.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        serializer = DeliverableSerializer(
            deliverable, data=request.data, partial=True, context={"project_id": project_id}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        deliverable = Deliverable.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        deliverable.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectWorkItemTypesEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        types = ensure_project_work_item_types(project)
        return Response(serialize_work_item_types(types), status=status.HTTP_200_OK)


class SOWImportEndpoint(BaseAPIView):
    """Upload a SOW (.xlsx / .pdf). With dry_run=true only the parsed summary is returned for review."""

    parser_classes = (MultiPartParser, FormParser)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"error": "Please upload the SOW file"}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > MAX_SOW_FILE_SIZE:
            return Response({"error": "The SOW file must be smaller than 10 MB"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data, errors, warnings = parse_sow(upload.name, upload.read())
        except SOWParseError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        dry_run = str(request.data.get("dry_run", "false")).lower() == "true"
        if errors:
            return Response(
                {"error": "The SOW has errors. Fix them and upload again.", "errors": errors, "warnings": warnings},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if dry_run:
            return Response(
                {"summary": build_summary(data), "errors": [], "warnings": warnings, "imported": False},
                status=status.HTTP_200_OK,
            )

        # {resource ID: user id} picked while reviewing the import
        resource_members = request.data.get("resource_members") or {}
        if isinstance(resource_members, str):
            try:
                resource_members = json.loads(resource_members)
            except ValueError:
                resource_members = {}
        if not isinstance(resource_members, dict):
            resource_members = {}

        summary = import_sow(
            project,
            data,
            resource_members={k: v for k, v in resource_members.items() if v},
            user=request.user,
        )
        mapped_resources = list(ProjectResource.objects.filter(project=project, member_id__isnull=False))
        bring_resource_members_in(project, mapped_resources, request)
        # the tasks go to the mapped members now that they are in the project (clients excepted)
        for resource in mapped_resources:
            sync_resource_assignees(resource)
        return Response(
            {"summary": summary, "errors": [], "warnings": warnings, "imported": True},
            status=status.HTTP_200_OK,
        )


def serialize_resources(resources):
    label_ids = [resource.label_id for resource in resources if resource.label_id]
    task_counts = {
        row["label_id"]: row
        for row in IssueLabel.objects.filter(label_id__in=label_ids, issue__deleted_at__isnull=True)
        .values("label_id")
        .annotate(
            task_count=Count("issue_id", distinct=True),
            done_count=Count(
                "issue_id", distinct=True, filter=Q(issue__state__group__in=DONE_STATE_GROUPS)
            ),
        )
    }
    return [
        {
            **ProjectResourceSerializer(resource).data,
            "task_count": task_counts.get(resource.label_id, {}).get("task_count", 0),
            "done_count": task_counts.get(resource.label_id, {}).get("done_count", 0),
        }
        for resource in resources
    ]


def bring_resource_members_in(project, resources, request):
    """The member who fills a resource joins the project (full access as a member) and gets the invite email."""
    for resource in resources:
        if resource.member_id:
            add_members_to_project(
                project,
                [resource.member_id],
                request.user.id,
                base_host(request=request, is_app=True),
                designation=resource.role,
            )


class ProjectResourceEndpoint(BaseAPIView):
    """Roles of the project (from the SOW or added manually) and the members mapped to them."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        resources = list(ProjectResource.objects.filter(workspace__slug=slug, project_id=project_id))
        return Response(serialize_resources(resources), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        project = Project.objects.get(workspace__slug=slug, pk=project_id)
        serializer = ProjectResourceSerializer(data=request.data, context={"project_id": project_id})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            resource = serializer.save(project_id=project_id)
            # Tasks are linked to a resource through its label in the "Resource" label group
            group = ensure_label(project, RESOURCE_GROUP, color=GROUP_COLORS[RESOURCE_GROUP])
            name = f"{resource.code} · {resource.role}" if resource.code else resource.role
            resource.label = ensure_label(
                project,
                name[:255],
                parent=group,
                description=" — ".join(filter(None, [resource.resource_type, resource.responsibilities])),
                color=GROUP_COLORS[RESOURCE_GROUP],
            )
            resource.save(update_fields=["label", "updated_at"])
        bring_resource_members_in(project, [resource], request)
        if resource.member_id:
            sync_resource_assignees(resource)
        return Response(serialize_resources([resource])[0], status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        resource = ProjectResource.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        previous_member_id = resource.member_id
        serializer = ProjectResourceSerializer(
            resource, data=request.data, partial=True, context={"project_id": project_id}
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            resource = serializer.save()
        if "member_id" in request.data:
            bring_resource_members_in(resource.project, [resource], request)
            sync_resource_assignees(resource, previous_member_id=previous_member_id)
        return Response(serialize_resources([resource])[0], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        resource = ProjectResource.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        # Keeps the label and the assignments on the work items
        resource.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkItemTreeEndpoint(BaseAPIView):
    """Every work item of the project in one response, for the Module / Milestone hierarchy view."""

    FIELDS = (
        "id",
        "name",
        "sequence_id",
        "project_id",
        "parent_id",
        "type_id",
        "milestone_id",
        "state_id",
        "priority",
        "start_date",
        "target_date",
        "sort_order",
        "completed_at",
        "archived_at",
        "is_draft",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "assignee_ids",
        "label_ids",
        "module_ids",
    )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        queryset = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id).order_by("sequence_id")
        issues = issue_queryset_grouper(queryset=queryset, group_by=None, sub_group_by=None).values(*self.FIELDS)
        return Response(list(issues), status=status.HTTP_200_OK)
