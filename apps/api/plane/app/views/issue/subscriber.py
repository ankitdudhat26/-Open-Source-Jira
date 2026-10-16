# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third Party imports
from rest_framework.response import Response
from rest_framework import status

# Module imports
from .. import BaseViewSet
from plane.app.serializers import IssueSubscriberSerializer
from plane.app.permissions import ProjectEntityPermission, ProjectLitePermission
from plane.db.models import Issue, IssueSubscriber, ProjectMember
from plane.utils.uuid import is_valid_uuid


class IssueSubscriberViewSet(BaseViewSet):
    serializer_class = IssueSubscriberSerializer
    model = IssueSubscriber

    permission_classes = [ProjectEntityPermission]

    def get_permissions(self):
        if self.action in ["subscribe", "unsubscribe", "subscription_status"]:
            self.permission_classes = [ProjectLitePermission]
        else:
            self.permission_classes = [ProjectEntityPermission]

        return super(IssueSubscriberViewSet, self).get_permissions()

    def perform_create(self, serializer):
        serializer.save(
            project_id=self.kwargs.get("project_id"),
            issue_id=self.kwargs.get("issue_id"),
        )

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .filter(project_id=self.kwargs.get("project_id"))
            .filter(issue_id=self.kwargs.get("issue_id"))
            .filter(
                project__project_projectmember__member=self.request.user,
                project__project_projectmember__is_active=True,
                project__archived_at__isnull=True,
            )
            .order_by("-created_at")
            .distinct()
        )

    def _watchers(self, slug, project_id, issue_id):
        """Active project members watching the work item, oldest first (like Jira's watcher list)."""
        return (
            IssueSubscriber.objects.filter(
                workspace__slug=slug,
                project_id=project_id,
                issue_id=issue_id,
                subscriber__member_project__project_id=project_id,
                subscriber__member_project__is_active=True,
                subscriber__is_active=True,
            )
            .order_by("created_at")
            .distinct()
        )

    def _watcher_response(self, slug, project_id, issue_id, response_status=status.HTTP_200_OK):
        watchers = self._watchers(slug, project_id, issue_id).values(
            "id", "subscriber_id", "created_at", "created_by_id"
        )
        return Response(
            [
                {
                    "id": str(watcher["id"]),
                    "subscriber": str(watcher["subscriber_id"]),
                    "created_at": watcher["created_at"],
                    "created_by": str(watcher["created_by_id"]) if watcher["created_by_id"] else None,
                }
                for watcher in watchers
            ],
            status=response_status,
        )

    def list(self, request, slug, project_id, issue_id):
        if not Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).exists():
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        return self._watcher_response(slug, project_id, issue_id)

    def create(self, request, slug, project_id, issue_id):
        """Add one or more project members as watchers: {"subscriber_ids": [...]} or {"subscriber": id}."""
        issue = Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
        if issue is None:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)

        subscriber_ids = request.data.get("subscriber_ids")
        if subscriber_ids is None and request.data.get("subscriber"):
            subscriber_ids = [request.data.get("subscriber")]
        if not isinstance(subscriber_ids, list) or not subscriber_ids:
            return Response(
                {"error": "subscriber_ids must be a non empty list of user ids."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        subscriber_ids = {str(subscriber_id) for subscriber_id in subscriber_ids}
        if not all(is_valid_uuid(subscriber_id) for subscriber_id in subscriber_ids):
            return Response({"error": "Invalid user id."}, status=status.HTTP_400_BAD_REQUEST)

        # only active members of this project can watch its work items
        member_ids = {
            str(member_id)
            for member_id in ProjectMember.objects.filter(
                workspace__slug=slug,
                project_id=project_id,
                member_id__in=subscriber_ids,
                is_active=True,
                member__is_active=True,
            ).values_list("member_id", flat=True)
        }
        invalid_ids = subscriber_ids - member_ids
        if invalid_ids:
            return Response(
                {"error": "Only active project members can be added as watchers.", "invalid_ids": sorted(invalid_ids)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_ids = {
            str(subscriber_id)
            for subscriber_id in IssueSubscriber.objects.filter(
                issue_id=issue_id, subscriber_id__in=member_ids
            ).values_list("subscriber_id", flat=True)
        }
        IssueSubscriber.objects.bulk_create(
            [
                IssueSubscriber(
                    issue_id=issue_id,
                    subscriber_id=subscriber_id,
                    project_id=project_id,
                    # bulk_create skips save(), which normally fills the workspace from the project
                    workspace_id=issue.workspace_id,
                    created_by=request.user,
                    updated_by=request.user,
                )
                for subscriber_id in sorted(member_ids - existing_ids)
            ],
            batch_size=50,
            ignore_conflicts=True,
        )
        return self._watcher_response(slug, project_id, issue_id, status.HTTP_201_CREATED)

    def destroy(self, request, slug, project_id, issue_id, subscriber_id):
        """Remove a watcher. subscriber_id is the watching user's id."""
        issue_subscriber = IssueSubscriber.objects.filter(
            project_id=project_id,
            subscriber_id=subscriber_id,
            workspace__slug=slug,
            issue_id=issue_id,
        ).first()
        if issue_subscriber is None:
            return Response({"error": "User is not watching this work item."}, status=status.HTTP_404_NOT_FOUND)
        issue_subscriber.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def subscribe(self, request, slug, project_id, issue_id):
        # watching twice is a no-op, so repeated clicks / two open tabs do not fail
        subscriber, created = IssueSubscriber.objects.get_or_create(
            issue_id=issue_id, subscriber_id=request.user.id, project_id=project_id
        )
        serializer = IssueSubscriberSerializer(subscriber)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def unsubscribe(self, request, slug, project_id, issue_id):
        IssueSubscriber.objects.filter(
            project=project_id,
            subscriber=request.user,
            workspace__slug=slug,
            issue=issue_id,
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def subscription_status(self, request, slug, project_id, issue_id):
        issue_subscriber = IssueSubscriber.objects.filter(
            issue=issue_id,
            subscriber=request.user,
            workspace__slug=slug,
            project=project_id,
        ).exists()
        return Response({"subscribed": issue_subscriber}, status=status.HTTP_200_OK)
