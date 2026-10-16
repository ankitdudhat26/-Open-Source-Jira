/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback } from "react";
import useSWR from "swr";
// services
import type { TProjectWorkflow } from "@/services/project/project-workflow.service";
import { ProjectWorkflowService } from "@/services/project/project-workflow.service";

export const projectWorkflowService = new ProjectWorkflowService();

export const PROJECT_WORKFLOW = (projectId: string) => `PROJECT_WORKFLOW_${projectId}`;

/**
 * States a work item in `fromStateId` may move to under the workflow (including the current state), or
 * `undefined` when it is not restricted (workflow off, or no rules for that state).
 */
export const getAllowedTargetStateIds = (
  workflow: TProjectWorkflow | undefined,
  fromStateId: string | null | undefined
): Set<string> | undefined => {
  if (!workflow?.is_enabled || !fromStateId) return undefined;
  const targets = workflow.transitions
    .filter((transition) => transition.from_state === fromStateId)
    .map((transition) => transition.to_state);
  if (targets.length === 0) return undefined;
  return new Set([fromStateId, ...targets]);
};

export const useProjectWorkflow = (
  workspaceSlug: string | undefined,
  projectId: string | undefined | null,
  enabled = true
) => {
  const { data, error, isLoading, mutate } = useSWR(
    enabled && workspaceSlug && projectId ? PROJECT_WORKFLOW(projectId) : null,
    enabled && workspaceSlug && projectId ? () => projectWorkflowService.getWorkflow(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false }
  );
  const getAllowedStateIds = useCallback(
    (fromStateId: string | null | undefined) => getAllowedTargetStateIds(data, fromStateId),
    [data]
  );
  return { workflow: data, error, isLoading, mutate, getAllowedStateIds };
};
