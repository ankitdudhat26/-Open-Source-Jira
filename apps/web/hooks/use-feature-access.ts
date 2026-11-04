/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUser, useUserPermissions } from "@/hooks/store/user";
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
 * Settings → Roles & access for the current user: `can(feature, action, fallback, projectId)` is what an admin set for
 * them (their custom access, else their role's rule); else false where the role's built-in rule denies it; else
 * `fallback` — the app's own rule (e.g. only the author edits a comment). The same in every project, new or cloned
 * from Jira, whatever their project role (a project role only lowers it).
 * Workspace admins, and Sub Admins in the projects they created, get `fallback` (the app's own rule); clients get what
 * an admin set, else `fallback`. Call it from an observer component.
 */
export const useFeatureAccess = (workspaceSlug?: string) => {
  const params = useParams();
  const slug = workspaceSlug ?? params.workspaceSlug?.toString();
  const { workspaceInfoBySlug, getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();
  const { data: currentUser } = useUser();
  const { getProjectById } = useProject();
  const { data: mine } = useSWR(slug ? ["MY_WORKSPACE_ACCESS", slug] : null, () =>
    workspaceAccessService.fetchMine(slug ?? "")
  );
  const workspaceRole = slug ? (workspaceInfoBySlug(slug)?.role as EUserPermissions | undefined) : undefined;

  const can = useCallback(
    (feature: string, action: TAccessAction, fallback: boolean, projectId?: string) => {
      if (!mine || mine.is_admin || !slug || workspaceRole === undefined) return fallback;
      if (workspaceRole === EUserPermissions.ADMIN) return fallback;
      let role = workspaceRole;
      if (projectId) {
        const projectRole = getProjectRoleByWorkspaceSlugAndProjectId(slug, projectId);
        // not in the project: the app's own rule
        if (projectRole === undefined) return fallback;
        // a Sub Admin has full access to the projects they created
        if (mine.is_sub_admin && currentUser?.id && getProjectById(projectId)?.created_by === currentUser.id)
          return fallback;
        role = Math.min(workspaceRole, projectRole);
      }
      const key: TAccessRole =
        role === EUserPermissions.MEMBER ? (mine.is_sub_admin ? "sub_admin" : "member") : "client";
      const value = mine.custom_access[feature]?.[action] ?? mine.rules[key]?.[feature]?.[action];
      if (typeof value === "boolean") return value;
      // what the built-in rules deny is hidden in every project; what they allow keeps the app's own rule
      if (mine.defaults?.[key]?.[feature]?.[action] === false) return false;
      return fallback;
    },
    [mine, slug, workspaceRole, currentUser?.id, getProjectById, getProjectRoleByWorkspaceSlugAndProjectId]
  );

  return { can };
};

/**
 * What the current user may do in a project's settings, by Settings → Roles & access (see `useFeatureAccess`): the
 * same in every project. Without a rule for them (admins, a Sub Admin's own projects) a project admin may.
 */
export const useProjectAccess = (workspaceSlug: string, projectId: string) => {
  const { allowPermissions } = useUserPermissions();
  const { can } = useFeatureAccess(workspaceSlug);
  const isProjectAdmin = allowPermissions(
    [EUserPermissions.ADMIN],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );
  return {
    /** details, features, lead and default assignee, automations: Projects → Edit */
    canEditProject: can("projects", "edit", isProjectAdmin, projectId),
    /** states, labels, estimates, custom fields, workflow: Project settings */
    canEditSettings: can("project_settings", "edit", isProjectAdmin, projectId),
    canAddMembers: can("project_members", "create", isProjectAdmin, projectId),
    canChangeMembers: can("project_members", "edit", isProjectAdmin, projectId),
    canRemoveMembers: can("project_members", "delete", isProjectAdmin, projectId),
  };
};

/** Add / change / delete in one project feature by Settings → Roles & access, else as project members may */
export const useFeatureActions = (feature: string, workspaceSlug: string, projectId: string) => {
  const { allowPermissions } = useUserPermissions();
  const { can } = useFeatureAccess(workspaceSlug);
  const isProjectMember = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );
  return {
    canView: can(feature, "view", true, projectId),
    canCreate: can(feature, "create", isProjectMember, projectId),
    canEdit: can(feature, "edit", isProjectMember, projectId),
    canDelete: can(feature, "delete", isProjectMember, projectId),
  };
};
