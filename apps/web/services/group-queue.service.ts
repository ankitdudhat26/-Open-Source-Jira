/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TGroupPermission = { key: string; label: string; description: string };

/** A group of people (e.g. DevOps) with rights and, optionally, a queue. */
export type TWorkspaceGroup = {
  id: string;
  name: string;
  description: string;
  color: string;
  has_queue: boolean;
  permissions: string[];
  is_default: boolean;
  member_ids: string[];
};

export type TQueueCounts = { open: number; unassigned: number; mine: number; done: number };

export type TQueueSummary = {
  group: { id: string; name: string; color: string };
  counts: TQueueCounts;
  is_member: boolean;
  can_self_assign: boolean;
  can_edit_assigned: boolean;
};

export type TQueueFilter = "unassigned" | "mine" | "open" | "done" | "all";

export type TQueueState = { id: string; name: string; group: string; color: string };

export type TQueueIssue = {
  id: string;
  name: string;
  sequence_id: number;
  key: string;
  project: { id: string; name: string; identifier: string };
  state: TQueueState | null;
  priority: string | null;
  type: string | null;
  assignee_ids: string[];
  is_mine: boolean;
  start_date: string | null;
  target_date: string | null;
  created_at: string;
  created_by: string | null;
};

export type TQueueComment = { id: string; actor: string; comment: string; created_at: string };

export type TQueueIssueDetail = TQueueIssue & {
  description: string;
  labels: string[];
  parent: { key: string; name: string } | null;
  can_self_assign: boolean;
  can_edit: boolean;
  can_comment: boolean;
  states: TQueueState[];
  comments: TQueueComment[];
};

export type TWorkItemQueue = { group_id: string | null; group_name: string | null };

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise
    .then((response) => response?.data)
    .catch((error) => {
      throw error?.response?.data;
    });

export class GroupQueueService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  getGroups(workspaceSlug: string): Promise<{ groups: TWorkspaceGroup[]; permissions: TGroupPermission[] }> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/groups/`));
  }

  createGroup(workspaceSlug: string, data: Partial<TWorkspaceGroup>): Promise<TWorkspaceGroup> {
    return unwrap(this.post(`/api/workspaces/${workspaceSlug}/groups/`, data));
  }

  updateGroup(workspaceSlug: string, groupId: string, data: Partial<TWorkspaceGroup>): Promise<TWorkspaceGroup> {
    return unwrap(this.patch(`/api/workspaces/${workspaceSlug}/groups/${groupId}/`, data));
  }

  deleteGroup(workspaceSlug: string, groupId: string): Promise<void> {
    return unwrap(this.delete(`/api/workspaces/${workspaceSlug}/groups/${groupId}/`));
  }

  getQueues(workspaceSlug: string): Promise<TQueueSummary[]> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/queues/`));
  }

  getQueueItems(workspaceSlug: string, groupId: string, filter: TQueueFilter): Promise<TQueueIssue[]> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/queues/${groupId}/items/`, { params: { filter } }));
  }

  getQueueItem(workspaceSlug: string, groupId: string, issueId: string): Promise<TQueueIssueDetail> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/queues/${groupId}/items/${issueId}/`));
  }

  updateQueueItem(
    workspaceSlug: string,
    groupId: string,
    issueId: string,
    data: Partial<{ state_id: string; priority: string; start_date: string | null; target_date: string | null }>
  ): Promise<TQueueIssue> {
    return unwrap(this.patch(`/api/workspaces/${workspaceSlug}/queues/${groupId}/items/${issueId}/`, data));
  }

  assignToMe(workspaceSlug: string, groupId: string, issueId: string): Promise<TQueueIssue> {
    return unwrap(this.post(`/api/workspaces/${workspaceSlug}/queues/${groupId}/items/${issueId}/assign/`));
  }

  unassignMe(workspaceSlug: string, groupId: string, issueId: string): Promise<TQueueIssue> {
    return unwrap(this.delete(`/api/workspaces/${workspaceSlug}/queues/${groupId}/items/${issueId}/assign/`));
  }

  addComment(workspaceSlug: string, groupId: string, issueId: string, comment: string): Promise<TQueueComment> {
    return unwrap(
      this.post(`/api/workspaces/${workspaceSlug}/queues/${groupId}/items/${issueId}/comments/`, { comment })
    );
  }

  getWorkItemQueue(workspaceSlug: string, projectId: string, issueId: string): Promise<TWorkItemQueue> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/queue/`));
  }

  setWorkItemQueue(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    groupId: string | null
  ): Promise<TWorkItemQueue> {
    return unwrap(
      this.put(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/queue/`, {
        group_id: groupId,
      })
    );
  }
}
