/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions } from "@plane/constants";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
import { useFeatureAccess } from "@/hooks/use-feature-access";

/**
 * What the current user's workspace role lets them do beyond working in their projects. A Sub Admin is a Member
 * (`is_sub_admin`) who can also create projects — with full access to them — and invite people as Member or Client.
 * Call it from an observer component.
 */
export const useWorkspaceRoleAccess = (workspaceSlug?: string) => {
  const params = useParams();
  const { workspaceInfoBySlug } = useUserPermissions();
  const slug = workspaceSlug ?? params.workspaceSlug?.toString();
  const membership = slug ? workspaceInfoBySlug(slug) : undefined;
  const role = membership?.role;
  const isAdmin = role === EUserPermissions.ADMIN;
  const isSubAdmin = role === EUserPermissions.MEMBER && !!membership?.is_sub_admin;
  // Settings → Roles & access can take these away from a role or person, or give them beyond the role
  const { can } = useFeatureAccess(slug);
  return {
    isAdmin,
    isSubAdmin,
    /** Admins and Sub Admins create projects; Members and Clients do not */
    canCreateProjects: can("projects", "create", isAdmin || isSubAdmin),
    /** Admins invite anyone; Sub Admins invite people as Member or Client */
    canInviteMembers: can("workspace_members", "create", isAdmin || isSubAdmin),
  };
};
