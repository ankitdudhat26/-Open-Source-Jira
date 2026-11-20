# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from itertools import groupby
from collections import defaultdict

# Django imports
from django.db import transaction
from django.db.models import Q
from django.db.utils import IntegrityError

# Third party imports
from rest_framework.response import Response
from rest_framework import status

# Module imports
from .. import BaseViewSet, BaseAPIView
from plane.app.serializers import StateSerializer
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import DraftIssue, Issue, State, WorkflowTransition
from plane.utils.cache import invalidate_cache
from plane.utils.uuid import is_valid_uuid
from plane.utils.workflow import mark_customized


class StateViewSet(BaseViewSet):
    serializer_class = StateSerializer
    model = State

    def get_queryset(self):
        return self.filter_queryset(
            super()
            .get_queryset()
            .filter(workspace__slug=self.kwargs.get("slug"))
            .filter(project_id=self.kwargs.get("project_id"))
            .filter(
                project__project_projectmember__member=self.request.user,
                project__project_projectmember__is_active=True,
                project__archived_at__isnull=True,
            )
            .filter(is_triage=False)
            .select_related("project")
            .select_related("workspace")
            .distinct()
        )

    @invalidate_cache(path="workspaces/:slug/states/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        try:
            serializer = StateSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(project_id=project_id)
                # the project no longer has only the default states: a new default leaves it alone
                mark_customized(project_id)
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            if "already exists" in str(e):
                return Response(
                    {"name": "The state name is already taken"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def partial_update(self, request, slug, project_id, pk):
        try:
            state = State.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
            before = (state.name, state.group)
            serializer = StateSerializer(state, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                # renamed or moved to another category (not just reordered or recoloured): customized
                if (serializer.instance.name, serializer.instance.group) != before:
                    mark_customized(project_id)
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as e:
            if "already exists" in str(e):
                return Response(
                    {"name": "The state name is already taken"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        states = StateSerializer(self.get_queryset(), many=True).data

        grouped_states = defaultdict(list)
        for state in states:
            grouped_states[state["group"]].append(state)

        for group, group_states in grouped_states.items():
            count = len(group_states)

            for index, state in enumerate(group_states, start=1):
                state["order"] = index / count

        grouped = request.GET.get("grouped", False)

        if grouped == "true":
            state_dict = {}
            for key, value in groupby(
                sorted(states, key=lambda state: state["group"]),
                lambda state: state.get("group"),
            ):
                state_dict[str(key)] = list(value)
            return Response(state_dict, status=status.HTTP_200_OK)

        return Response(states, status=status.HTTP_200_OK)

    @invalidate_cache(path="workspaces/:slug/states/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def mark_as_default(self, request, slug, project_id, pk):
        # Select all the states which are marked as default
        _ = State.objects.filter(workspace__slug=slug, project_id=project_id, default=True).update(default=False)
        _ = State.objects.filter(workspace__slug=slug, project_id=project_id, pk=pk).update(default=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @invalidate_cache(path="workspaces/:slug/states/", url_params=True, user=False)
    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, slug, project_id, pk):
        state = State.objects.get(is_triage=False, pk=pk, project_id=project_id, workspace__slug=slug)

        if state.default:
            return Response(
                {"error": "Default state cannot be deleted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # its work items (also archived ones and drafts) move to the status picked in the delete dialog
        work_items = Issue.all_objects.filter(state_id=pk, deleted_at__isnull=True)
        drafts = DraftIssue.all_objects.filter(state_id=pk, deleted_at__isnull=True)
        if work_items.exists() or drafts.exists():
            move_to = request.query_params.get("move_to") or request.data.get("move_to")
            target = (
                State.objects.filter(pk=move_to, project_id=project_id).exclude(pk=pk).first()
                if move_to and is_valid_uuid(str(move_to))
                else None
            )
            if target is None:
                return Response(
                    {"error": "This status has work items. Choose the status to move them to."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            with transaction.atomic():
                work_items.update(state=target)
                drafts.update(state=target)

        state.delete()
        # its permitted moves go with it, and the project's workflow is now its own
        for transition in WorkflowTransition.objects.filter(Q(from_state_id=pk) | Q(to_state_id=pk)):
            transition.delete(soft=False)
        mark_customized(project_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class IntakeStateEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        state = State.triage_objects.filter(workspace__slug=slug, project_id=project_id).first()
        if not state:
            return Response(
                {"error": "Triage state not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(StateSerializer(state).data, status=status.HTTP_200_OK)
