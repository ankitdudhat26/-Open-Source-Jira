# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Settings → Roles & access: what each role may do in each feature, and custom access for one person. Workspace
admins manage it; every member reads what applies to them so the app shows what they can use."""

from rest_framework import status
from rest_framework.response import Response

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Workspace, WorkspaceAccessPolicy, WorkspaceMember
from plane.utils.access_control import (
    DEFAULTS,
    FEATURE_ACTIONS,
    FEATURES,
    ROLE_LABELS,
    ROLES,
    effective_access,
    policy_rules,
    role_key,
)

CUSTOM_VALUES = {"allow": True, "deny": False}


def _features():
    return [
        {
            **{key: feature[key] for key in ("key", "label", "description", "scope", "actions", "action_labels")},
            # viewing it is not settable: everyone in the project or workspace sees it
            "always_visible": "view" not in feature["actions"] and feature["key"] not in ("exports", "all_projects"),
        }
        for feature in FEATURES
    ]


def _valid_cell(feature, action):
    return action in FEATURE_ACTIONS.get(feature, ())


def _member_data(membership):
    member = membership.member
    return {
        "id": str(membership.id),
        "member_id": str(member.id),
        "display_name": member.display_name,
        "full_name": f"{member.first_name or ''} {member.last_name or ''}".strip(),
        "email": member.email,
        "role": role_key(membership.role, membership.is_sub_admin),
        "custom_access": membership.custom_access or {},
        "access": effective_access(membership),
    }


class WorkspaceAccessEndpoint(BaseAPIView):
    """The role rules: GET everything the settings page needs; PATCH one cell; DELETE resets a role."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        rules = policy_rules(workspace.id)
        people = WorkspaceMember.objects.filter(workspace=workspace, is_active=True, member__is_bot=False).exclude(
            custom_access={}
        )
        return Response(
            {
                "features": _features(),
                "roles": [{"key": key, "label": ROLE_LABELS[key]} for key in ROLES],
                "defaults": DEFAULTS,
                "rules": rules,
                "custom_count": people.count(),
            },
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug):
        """One cell ({role, feature, action, allowed}) or several of one role ({role, cells: [{feature, action,
        allowed}]}), saved together."""
        role = request.data.get("role")
        cells = request.data.get("cells")
        if cells is None:
            cells = [{key: request.data.get(key) for key in ("feature", "action", "allowed")}]
        if (
            role not in ROLES
            or not isinstance(cells, list)
            or not cells
            or any(
                not isinstance(cell, dict)
                or not _valid_cell(cell.get("feature"), cell.get("action"))
                or not isinstance(cell.get("allowed"), bool)
                for cell in cells
            )
        ):
            return Response({"error": "Choose a role, a feature and an action."}, status=status.HTTP_400_BAD_REQUEST)
        workspace = Workspace.objects.get(slug=slug)
        # one per workspace, also counting a deleted one: bring it back rather than adding another
        policy = WorkspaceAccessPolicy.all_objects.filter(workspace=workspace).first()
        if policy is None:
            policy = WorkspaceAccessPolicy.objects.create(workspace=workspace)
        elif policy.deleted_at:
            policy.deleted_at = None
            policy.rules = {}
        rules = policy.rules or {}
        for cell in cells:
            feature, action, allowed = cell["feature"], cell["action"], cell["allowed"]
            features = rules.setdefault(role, {})
            actions = features.setdefault(feature, {})
            # the same as the built-in rule: nothing to keep, so the code keeps deciding it
            if allowed == DEFAULTS[role][feature][action]:
                actions.pop(action, None)
            else:
                actions[action] = allowed
            if not actions:
                features.pop(feature, None)
        if not rules.get(role):
            rules.pop(role, None)
        policy.rules = rules
        policy.save(update_fields=["rules", "updated_at", "deleted_at"])
        return Response({"rules": rules}, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug):
        role = request.query_params.get("role")
        if role not in ROLES:
            return Response({"error": "Choose a role to reset."}, status=status.HTTP_400_BAD_REQUEST)
        policy = WorkspaceAccessPolicy.objects.filter(workspace__slug=slug).first()
        if policy and role in (policy.rules or {}):
            policy.rules.pop(role)
            policy.save(update_fields=["rules", "updated_at"])
        return Response({"rules": policy.rules if policy else {}}, status=status.HTTP_200_OK)


class WorkspaceMemberAccessEndpoint(BaseAPIView):
    """Custom access for one person: GET it with what they end up with; PATCH one cell; DELETE resets them."""

    def _membership(self, slug, member_id):
        return (
            WorkspaceMember.objects.filter(workspace__slug=slug, member_id=member_id, is_active=True)
            .select_related("member")
            .first()
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, member_id):
        membership = self._membership(slug, member_id)
        if not membership:
            return Response({"error": "This person is not in the workspace."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_member_data(membership), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, member_id):
        membership = self._membership(slug, member_id)
        if not membership:
            return Response({"error": "This person is not in the workspace."}, status=status.HTTP_404_NOT_FOUND)
        if membership.role == ROLE.ADMIN.value:
            return Response({"error": "Admins always have full access."}, status=status.HTTP_400_BAD_REQUEST)
        # one cell ({feature, action, value}) or several ({cells: [{feature, action, value}]}), saved together
        cells = request.data.get("cells")
        if cells is None:
            cells = [{key: request.data.get(key) for key in ("feature", "action", "value")}]
        if (
            not isinstance(cells, list)
            or not cells
            or any(
                not isinstance(cell, dict)
                or not _valid_cell(cell.get("feature"), cell.get("action"))
                or cell.get("value") not in ("allow", "deny", "default")
                for cell in cells
            )
        ):
            return Response(
                {"error": "Choose a feature, an action and allow, deny or default."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        custom = membership.custom_access or {}
        for cell in cells:
            feature, action, value = cell["feature"], cell["action"], cell["value"]
            actions = custom.setdefault(feature, {})
            if value == "default":
                actions.pop(action, None)
            else:
                actions[action] = CUSTOM_VALUES[value]
            if not actions:
                custom.pop(feature, None)
        membership.custom_access = custom
        membership.save(update_fields=["custom_access", "updated_at"])
        return Response(_member_data(membership), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, member_id):
        membership = self._membership(slug, member_id)
        if not membership:
            return Response({"error": "This person is not in the workspace."}, status=status.HTTP_404_NOT_FOUND)
        membership.custom_access = {}
        membership.save(update_fields=["custom_access", "updated_at"])
        return Response(_member_data(membership), status=status.HTTP_200_OK)


class WorkspaceAccessPeopleEndpoint(BaseAPIView):
    """The people with custom access, for the settings page's list."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        people = (
            WorkspaceMember.objects.filter(workspace__slug=slug, is_active=True, member__is_bot=False)
            .exclude(custom_access={})
            .select_related("member")
            .order_by("member__first_name", "member__display_name")
        )
        return Response([_member_data(membership) for membership in people], status=status.HTTP_200_OK)


class MyWorkspaceAccessEndpoint(BaseAPIView):
    """What the settings set for the current user — the app hides what is denied and shows what is allowed."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        membership = WorkspaceMember.objects.filter(workspace__slug=slug, member=request.user, is_active=True).first()
        is_admin = membership.role == ROLE.ADMIN.value
        return Response(
            {
                "is_admin": is_admin,
                "is_sub_admin": membership.is_sub_admin,
                # the same in every project: a project role only lowers them, Sub Admins keep their own projects
                "rules": {} if is_admin else policy_rules(membership.workspace_id),
                "custom_access": {} if is_admin else (membership.custom_access or {}),
                # the built-in rules, which apply where nothing is set (clients keep the code's read-only rules)
                "defaults": {} if is_admin else {key: DEFAULTS[key] for key in ("sub_admin", "member")},
            },
            status=status.HTTP_200_OK,
        )
