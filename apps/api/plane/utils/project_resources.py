# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
from plane.db.models import IssueAssignee, IssueLabel, ProjectMember


def is_assignable_member(project_id, user_id):
    """Only active members and admins of the project can be assigned work."""
    return ProjectMember.objects.filter(
        project_id=project_id, member_id=user_id, role__gte=15, is_active=True
    ).exists()


def sync_resource_assignees(resource, previous_member_id=None):
    """Assign the work items of a resource (those carrying its label) to the member mapped to it.

    When the mapping changes, the previous member is unassigned from those work items.
    Returns the number of work items newly assigned.
    """
    if not resource.label_id:
        return 0
    issue_ids = list(
        IssueLabel.objects.filter(
            label_id=resource.label_id,
            issue__project_id=resource.project_id,
            issue__deleted_at__isnull=True,
        ).values_list("issue_id", flat=True)
    )
    if not issue_ids:
        return 0

    if previous_member_id and str(previous_member_id) != str(resource.member_id):
        IssueAssignee.objects.filter(issue_id__in=issue_ids, assignee_id=previous_member_id).delete(soft=False)

    if not resource.member_id:
        return 0
    already_assigned = set(
        IssueAssignee.objects.filter(issue_id__in=issue_ids, assignee_id=resource.member_id).values_list(
            "issue_id", flat=True
        )
    )
    created = IssueAssignee.objects.bulk_create(
        [
            IssueAssignee(
                issue_id=issue_id,
                assignee_id=resource.member_id,
                project_id=resource.project_id,
                workspace_id=resource.workspace_id,
            )
            for issue_id in issue_ids
            if issue_id not in already_assigned
        ],
        ignore_conflicts=True,
    )
    return len(created)
