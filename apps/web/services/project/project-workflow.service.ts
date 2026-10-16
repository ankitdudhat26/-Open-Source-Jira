/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

/** A permitted state change; `reviewer_ids` limits who can make it (empty: every member). */
export type TWorkflowTransition = {
  id?: string;
  from_state: string;
  to_state: string;
  reviewer_ids: string[];
};

export type TWorkflowTemplate = { key: string; name: string; description: string };

export type TProjectWorkflow = {
  is_enabled: boolean;
  transitions: TWorkflowTransition[];
  templates: TWorkflowTemplate[];
};

export class ProjectWorkflowService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/workflow/`;
  }

  async getWorkflow(workspaceSlug: string, projectId: string): Promise<TProjectWorkflow> {
    return this.get(this.url(workspaceSlug, projectId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async saveWorkflow(
    workspaceSlug: string,
    projectId: string,
    data: { is_enabled: boolean; transitions: TWorkflowTransition[] }
  ): Promise<TProjectWorkflow> {
    return this.put(this.url(workspaceSlug, projectId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async applyTemplate(workspaceSlug: string, projectId: string, template: string): Promise<TProjectWorkflow> {
    return this.post(`${this.url(workspaceSlug, projectId)}apply-template/`, { template })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
