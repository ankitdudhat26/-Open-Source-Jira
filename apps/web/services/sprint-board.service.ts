/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

/** A work item of the sprint, or (in_sprint: false) a parent feature of one. */
export type TSprintBoardItem = {
  id: string;
  name: string;
  sequence_id: number;
  project_id: string;
  parent_id: string | null;
  type_id: string | null;
  state_id: string | null;
  priority: string | null;
  start_date: string | null;
  target_date: string | null;
  completed_at: string | null;
  assignee_ids: string[];
  in_sprint: boolean;
};

export class SprintBoardService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getSprintBoard(workspaceSlug: string, projectId: string, cycleId: string): Promise<TSprintBoardItem[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/cycles/${cycleId}/sprint-board/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
