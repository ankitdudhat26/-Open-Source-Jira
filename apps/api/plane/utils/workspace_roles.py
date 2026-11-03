# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace roles beyond Admin / Member / Client: a Sub Admin is a Member (role 15) with `is_sub_admin` — they can
also create projects (getting full access to them) and invite people as Member or Client."""

from plane.db.models import WorkspaceMember

ADMIN = 20
MEMBER = 15


def workspace_membership(user, slug):
    return WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True).first()


def is_sub_admin(membership):
    return bool(membership and membership.role == MEMBER and membership.is_sub_admin)


def can_create_projects(user, slug):
    """Admins and Sub Admins create projects; Members and Clients work in the projects they are added to."""
    membership = workspace_membership(user, slug)
    return bool(membership and (membership.role == ADMIN or is_sub_admin(membership)))


def can_invite_members(user, slug):
    """Admins invite anyone; Sub Admins invite people as Member or Client (never Admin or Sub Admin)."""
    membership = workspace_membership(user, slug)
    return bool(membership and (membership.role == ADMIN or is_sub_admin(membership)))
