/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
// services
import { customFieldService } from "@/services/custom-field.service";

export const PROJECT_CUSTOM_FIELDS = (projectId: string) => `PROJECT_CUSTOM_FIELDS_${projectId}`;
export const ISSUE_CUSTOM_FIELD_VALUES = (issueId: string) => `ISSUE_CUSTOM_FIELD_VALUES_${issueId}`;

export const useProjectCustomFields = (workspaceSlug: string | undefined, projectId: string | undefined) => {
  const { data, mutate, isLoading } = useSWR(
    workspaceSlug && projectId ? PROJECT_CUSTOM_FIELDS(projectId) : null,
    workspaceSlug && projectId ? () => customFieldService.list(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false }
  );
  return { fields: data, mutate, isLoading };
};

export const useIssueCustomFieldValues = (
  workspaceSlug: string | undefined,
  projectId: string | undefined,
  issueId: string | undefined
) => {
  const { data, mutate } = useSWR(
    workspaceSlug && projectId && issueId ? ISSUE_CUSTOM_FIELD_VALUES(issueId) : null,
    workspaceSlug && projectId && issueId
      ? () => customFieldService.getValues(workspaceSlug, projectId, issueId)
      : null,
    { revalidateOnFocus: false }
  );
  return { values: data, mutate };
};
