/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback } from "react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions } from "@plane/constants";
import type { TIssue } from "@plane/types";
// hooks
import { useUser, useUserPermissions } from "@/hooks/store/user";

type TWorkItemOwnership = Pick<TIssue, "created_by" | "project_id">;

/** Whether the properties of the work items of a project — or of the given work item — can be edited. */
export type TCanEditProperties = (projectId: string | undefined, issue?: TWorkItemOwnership) => boolean;

/**
 * Clients (the guests of a project) create work items and edit the ones they created — every detail, the status
 * included. Members and admins keep editing any work item; archiving and deleting stay with them.
 */
export const useClientWorkItemAccess = () => {
  const { workspaceSlug } = useParams();
  const { data: currentUser } = useUser();
  const { getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();

  const isProjectClient = useCallback(
    (projectId: string | null | undefined) =>
      !!workspaceSlug &&
      !!projectId &&
      getProjectRoleByWorkspaceSlugAndProjectId(workspaceSlug.toString(), projectId) === EUserPermissions.GUEST,
    [workspaceSlug, getProjectRoleByWorkspaceSlugAndProjectId]
  );

  const canClientEditWorkItem = useCallback(
    (issue: TWorkItemOwnership | undefined) =>
      !!issue && !!currentUser?.id && issue.created_by === currentUser.id && isProjectClient(issue.project_id),
    [currentUser?.id, isProjectClient]
  );

  return { isProjectClient, canClientEditWorkItem };
};
