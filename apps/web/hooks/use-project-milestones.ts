/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect } from "react";
import { observable, runInAction } from "mobx";
import useSWR from "swr";
// plane imports
import type { TMilestone, TWorkItemType, TWorkItemTypeKey } from "@plane/types";
// services
import { ProjectMilestoneService } from "@/services/project/project-milestone.service";

export const projectMilestoneService = new ProjectMilestoneService();

/**
 * Latest work item types / milestones per project, readable outside React (e.g. by the group by column builders).
 * Kept in sync by the hooks below.
 */
export const workItemTypesByProject = observable.map<string, TWorkItemType[]>({}, { deep: false });
export const milestonesByProject = observable.map<string, TMilestone[]>({}, { deep: false });

export const PROJECT_MILESTONES = (projectId: string) => `PROJECT_MILESTONES_${projectId}`;
export const PROJECT_DELIVERABLES = (projectId: string) => `PROJECT_DELIVERABLES_${projectId}`;
export const PROJECT_RESOURCES = (projectId: string) => `PROJECT_RESOURCES_${projectId}`;
export const PROJECT_WORK_ITEM_TYPES = (projectId: string) => `PROJECT_WORK_ITEM_TYPES_${projectId}`;

export const useProjectMilestones = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { data, error, isLoading, mutate } = useSWR(
    workspaceSlug && projectId ? PROJECT_MILESTONES(projectId) : null,
    workspaceSlug && projectId ? () => projectMilestoneService.getMilestones(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false }
  );
  useEffect(() => {
    if (projectId && data) runInAction(() => milestonesByProject.set(projectId, data));
  }, [projectId, data]);
  return { milestones: data, error, isLoading, mutate };
};

export const useProjectDeliverables = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { data, error, isLoading, mutate } = useSWR(
    workspaceSlug && projectId ? PROJECT_DELIVERABLES(projectId) : null,
    workspaceSlug && projectId ? () => projectMilestoneService.getDeliverables(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false }
  );
  return { deliverables: data, error, isLoading, mutate };
};

export const useProjectResources = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { data, error, isLoading, mutate } = useSWR(
    workspaceSlug && projectId ? PROJECT_RESOURCES(projectId) : null,
    workspaceSlug && projectId ? () => projectMilestoneService.getResources(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false }
  );
  return { resources: data, error, isLoading, mutate };
};

/** Feature / Task / Bug work item types of a project. */
export const useProjectWorkItemTypes = (workspaceSlug: string | undefined, projectId: string | undefined | null) => {
  const { data } = useSWR(
    workspaceSlug && projectId ? PROJECT_WORK_ITEM_TYPES(projectId) : null,
    workspaceSlug && projectId ? () => projectMilestoneService.getWorkItemTypes(workspaceSlug, projectId) : null,
    { revalidateIfStale: false, revalidateOnFocus: false }
  );
  useEffect(() => {
    if (projectId && data) runInAction(() => workItemTypesByProject.set(projectId, data));
  }, [projectId, data]);

  const getTypeById = useCallback(
    (typeId: string | null | undefined): TWorkItemType | undefined =>
      typeId ? data?.find((type) => type.id === typeId) : undefined,
    [data]
  );
  const getTypeByKey = useCallback(
    (key: TWorkItemTypeKey): TWorkItemType | undefined => data?.find((type) => type.key === key),
    [data]
  );

  return {
    workItemTypes: data,
    defaultWorkItemType: data?.find((type) => type.is_default),
    getTypeById,
    getTypeByKey,
  };
};
