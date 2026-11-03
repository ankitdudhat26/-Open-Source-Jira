/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { EUserPermissions } from "@plane/constants";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// services
import type { TAccessAction, TAccessRole } from "@/services/workspace-access.service";
import { workspaceAccessService } from "@/services/workspace-access.service";

/** The Roles & access feature of each project navigation item */
export const NAV_ITEM_FEATURES: Record<string, string> = {
  work_items: "work_items",
  milestones: "milestones",
  resources: "resources",
  cycles: "sprints",
  modules: "modules",
  views: "views",
  pages: "pages",
  intake: "intake",
};

/**
 * Settings → Roles & access for the current user: `can(feature, action, fallback, projectId)` is what an admin set
 * for them (their custom access, else their role's rule) or `fallback` — the app's own rule — where nothing is set.
 * In a project the rules of their project role apply; admins and project admins always get `fallback`.
 * Call it from an observer component.
 */
export const useFeatureAccess = (workspaceSlug?: string) => {
  const params = useParams();
  const slug = workspaceSlug ?? params.workspaceSlug?.toString();
  const { workspaceInfoBySlug, getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();
  const { data: mine } = useSWR(slug ? ["MY_WORKSPACE_ACCESS", slug] : null, () =>
    workspaceAccessService.fetchMine(slug ?? "")
  );
  const membership = slug ? workspaceInfoBySlug(slug) : undefined;

  const can = useCallback(
    (feature: string, action: TAccessAction, fallback: boolean, projectId?: string) => {
      if (!mine || mine.is_admin || !slug) return fallback;
      const role = projectId
        ? getProjectRoleByWorkspaceSlugAndProjectId(slug, projectId)
        : (membership?.role as EUserPermissions | undefined);
      if (role === undefined || role === EUserPermissions.ADMIN) return fallback;
      const key: TAccessRole =
        role === EUserPermissions.MEMBER ? (mine.is_sub_admin ? "sub_admin" : "member") : "client";
      const value = mine.custom_access[feature]?.[action] ?? mine.rules[key]?.[feature]?.[action];
      return typeof value === "boolean" ? value : fallback;
    },
    [mine, slug, membership?.role, getProjectRoleByWorkspaceSlugAndProjectId]
  );

  return { can };
};
