/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
// services
import { GroupQueueService } from "@/services/group-queue.service";

export const groupQueueService = new GroupQueueService();

export const WORKSPACE_GROUPS = (workspaceSlug: string) => `WORKSPACE_GROUPS_${workspaceSlug}`;
export const WORKSPACE_QUEUES = (workspaceSlug: string) => `WORKSPACE_QUEUES_${workspaceSlug}`;

export const useWorkspaceGroups = (workspaceSlug: string | undefined) => {
  const { data, error, isLoading, mutate } = useSWR(
    workspaceSlug ? WORKSPACE_GROUPS(workspaceSlug) : null,
    workspaceSlug ? () => groupQueueService.getGroups(workspaceSlug) : null,
    { revalidateOnFocus: false }
  );
  return { groups: data?.groups, permissions: data?.permissions, error, isLoading, mutate };
};

/** Queues the current user can open, with their counts; refreshed every minute for the sidebar badge. */
export const useWorkspaceQueues = (workspaceSlug: string | undefined) => {
  const { data, error, isLoading, mutate } = useSWR(
    workspaceSlug ? WORKSPACE_QUEUES(workspaceSlug) : null,
    workspaceSlug ? () => groupQueueService.getQueues(workspaceSlug) : null,
    { refreshInterval: 60_000 }
  );
  return { queues: data, error, isLoading, mutate };
};
