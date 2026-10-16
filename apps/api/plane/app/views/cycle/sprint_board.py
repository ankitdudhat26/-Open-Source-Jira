# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Cycle, CycleIssue, Issue
from plane.utils.grouper import issue_queryset_grouper

# a broken (cyclic) parent chain stops here
MAX_DEPTH = 20


class SprintBoardEndpoint(BaseAPIView):
    """Every work item of a sprint (cycle) with its parent features, for the sprint's feature / task view.

    Parents outside the sprint are included with ``in_sprint: false`` so their tasks can still be shown under them.
    """

    FIELDS = (
        "id",
        "name",
        "sequence_id",
        "project_id",
        "parent_id",
        "type_id",
        "state_id",
        "priority",
        "start_date",
        "target_date",
        "completed_at",
        "created_at",
        "assignee_ids",
        "estimate_point",
    )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, cycle_id):
        if not Cycle.objects.filter(workspace__slug=slug, project_id=project_id, pk=cycle_id).exists():
            return Response({"error": "Sprint not found"}, status=status.HTTP_404_NOT_FOUND)
        sprint_ids = {
            str(issue_id)
            for issue_id in CycleIssue.objects.filter(
                workspace__slug=slug,
                project_id=project_id,
                cycle_id=cycle_id,
                issue__deleted_at__isnull=True,
            ).values_list("issue_id", flat=True)
        }
        # parents (and their parents) of the sprint's work items
        all_ids = set(sprint_ids)
        frontier = set(sprint_ids)
        for _ in range(MAX_DEPTH):
            parent_ids = {
                str(parent_id)
                for parent_id in Issue.issue_objects.filter(pk__in=frontier, parent_id__isnull=False).values_list(
                    "parent_id", flat=True
                )
            } - all_ids
            if not parent_ids:
                break
            all_ids |= parent_ids
            frontier = parent_ids

        queryset = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk__in=all_ids).order_by(
            "sequence_id"
        )
        issues = issue_queryset_grouper(queryset=queryset, group_by=None, sub_group_by=None).values(*self.FIELDS)
        return Response(
            [{**issue, "in_sprint": str(issue["id"]) in sprint_ids} for issue in issues],
            status=status.HTTP_200_OK,
        )
