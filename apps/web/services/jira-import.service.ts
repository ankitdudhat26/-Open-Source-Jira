/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TJiraConnection =
  | { connected: false }
  | { connected: true; site_url: string; email: string; account_name: string; verified_at: string | null };

export type TJiraProject = {
  id: string;
  key: string;
  name: string;
  type: string | null;
  lead: string | null;
  linked_project: { id: string; name: string; identifier: string } | null;
  last_synced_at: string | null;
};

export type TJiraSyncOptions = {
  comments?: boolean;
  history?: boolean;
  attachments?: boolean;
  full?: boolean;
  /** "users": a user sync (every active Jira person joins the workspace) */
  kind?: "users";
};

export type TJiraSyncRun = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  project_keys: string[];
  options: TJiraSyncOptions;
  current_step: string;
  stats: Record<string, number>;
  projects: Record<string, { project_id: string; name: string }>;
  warnings: string[];
  unmatched_users: { account_id: string; name: string; email: string }[];
  error: string;
  initiated_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type THistoryEntry = {
  id: string;
  created_at: string;
  actor: { id: string; display_name: string; avatar_url: string | null } | null;
  project: { id: string; name: string; identifier: string };
  issue: { id: string; sequence_id: number; name: string };
  verb: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  comment: string;
  /** the person / field as named in Jira (people without an account here too) */
  actor_name: string;
  field_label: string;
  from_jira: boolean;
};

export type THistoryFilters = {
  project_id?: string;
  actor_id?: string;
  field?: string;
  source?: "jira" | "";
  from?: string;
  to?: string;
  search?: string;
};

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise
    .then((response) => response?.data)
    .catch((error) => {
      throw error?.response?.data;
    });

export class JiraImportService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  getConnection(workspaceSlug: string): Promise<TJiraConnection> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/jira/connection/`));
  }

  saveConnection(
    workspaceSlug: string,
    data: { site_url: string; email: string; api_token: string }
  ): Promise<TJiraConnection> {
    return unwrap(this.put(`/api/workspaces/${workspaceSlug}/jira/connection/`, data));
  }

  deleteConnection(workspaceSlug: string): Promise<void> {
    return unwrap(this.delete(`/api/workspaces/${workspaceSlug}/jira/connection/`));
  }

  getProjects(workspaceSlug: string): Promise<TJiraProject[]> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/jira/projects/`));
  }

  getRuns(workspaceSlug: string): Promise<TJiraSyncRun[]> {
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/jira/syncs/`));
  }

  startSync(workspaceSlug: string, projectKeys: string[], options: TJiraSyncOptions): Promise<TJiraSyncRun> {
    return unwrap(this.post(`/api/workspaces/${workspaceSlug}/jira/syncs/`, { project_keys: projectKeys, options }));
  }

  startUserSync(workspaceSlug: string): Promise<TJiraSyncRun> {
    return unwrap(this.post(`/api/workspaces/${workspaceSlug}/jira/syncs/`, { kind: "users" }));
  }

  getHistory(
    workspaceSlug: string,
    filters: THistoryFilters,
    page: number
  ): Promise<{ results: THistoryEntry[]; page: number; has_more: boolean }> {
    const params = Object.fromEntries(Object.entries({ ...filters, page }).filter(([, value]) => value));
    return unwrap(this.get(`/api/workspaces/${workspaceSlug}/history/`, { params }));
  }
}

export const jiraImportService = new JiraImportService();
