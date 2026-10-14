/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TMilestoneFormData = {
  name: string;
  amount: string | null;
};

export type TMilestoneModuleProgress = {
  module_id: string;
  total_issues: number;
  done_issues: number;
  is_completed: boolean;
};

export type TMilestone = {
  id: string;
  code: string;
  name: string;
  amount: string | null;
  payment_percentage: string | null;
  // scope / acceptance criteria
  description: string;
  sort_order: number;
  module_ids: string[];
  project: string;
  workspace: string;
  external_source: string | null;
  external_id: string | null;
  created_at: string;
  updated_at: string;
  // progress of the work items delivered in this milestone
  total_issues: number;
  completed_issues: number;
  cancelled_issues: number;
  is_completed: boolean;
  modules: TMilestoneModuleProgress[];
};

export type TMilestonePayload = Partial<Pick<TMilestone, "name" | "amount" | "payment_percentage" | "description">> & {
  module_ids?: string[];
};

export type TDeliverable = {
  id: string;
  code: string;
  name: string;
  description: string;
  milestone_id: string | null;
  sort_order: number;
  project: string;
  workspace: string;
  created_at: string;
  updated_at: string;
};

export type TDeliverablePayload = Partial<Pick<TDeliverable, "name" | "description" | "milestone_id">>;

export type TWorkItemTypeKey = "feature" | "task" | "bug";

export type TWorkItemType = {
  id: string;
  key: TWorkItemTypeKey;
  name: string;
  description: string;
  is_default: boolean;
  color: string;
};

export type TSOWImportSummary = {
  counts: {
    milestones: number;
    deliverables: number;
    resources: number;
    modules: number;
    features: number;
    tasks: number;
  };
  milestones: {
    id: string;
    name: string;
    payment_percentage: string | null;
    amount: string | null;
    scope: string;
    modules: { id: string; name: string }[];
    deliverables: string[];
    feature_count: number;
    task_count: number;
  }[];
  deliverables: { id: string; name: string; description: string; milestone_id: string }[];
  resources: { id: string; role: string; resource_type: string; responsibilities: string; task_count: number }[];
  modules: { id: string; name: string; scope: string; feature_count: number; task_count: number }[];
};

export type TSOWImportResponse = {
  summary: TSOWImportSummary;
  errors: string[];
  warnings: string[];
  imported: boolean;
};

export type TSOWImportError = {
  error: string;
  errors?: string[];
  warnings?: string[];
};

export type TProjectResource = {
  id: string;
  code: string;
  role: string;
  resource_type: string;
  responsibilities: string;
  member_id: string | null;
  label_id: string | null;
  sort_order: number;
  // work items carrying the resource's label
  task_count: number;
  done_count: number;
};

export type TProjectResourcePayload = Partial<
  Pick<TProjectResource, "code" | "role" | "resource_type" | "responsibilities" | "member_id">
>;
