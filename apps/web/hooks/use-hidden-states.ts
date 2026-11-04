/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useParams } from "next/navigation";
// plane imports
import { EIssuesStoreType } from "@plane/types";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
import { useIssueStoreType } from "@/hooks/use-issue-layout-store";

/**
 * The statuses the user hid on the project's work items screen (the Statuses menu next to Display). Their work items
 * are not fetched; the layouts leave out their columns too. Other screens (sprints, modules, views) show every status.
 * Call it from an observer component.
 */
export const useHiddenStateIds = (): string[] => {
  const { projectId } = useParams();
  const storeType = useIssueStoreType();
  const { issuesFilter } = useIssues(EIssuesStoreType.PROJECT);
  if (storeType !== EIssuesStoreType.PROJECT || !projectId) return [];
  return issuesFilter.getIssueFilters(projectId.toString())?.displayFilters?.hidden_state_ids ?? [];
};
