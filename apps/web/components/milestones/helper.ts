/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TMilestone } from "@plane/types";

const amountFormatter = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const formatAmount = (amount: string | number | null | undefined) => {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = Number(amount);
  return Number.isNaN(value) ? "—" : amountFormatter.format(value);
};

export const formatPercentage = (value: string | number | null | undefined) => {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isNaN(number) ? "—" : `${Number.isInteger(number) ? number : number.toFixed(2)}%`;
};

export type TMilestoneStatus = "completed" | "in_progress" | "not_started";

export const getMilestoneStatus = (milestone: TMilestone): TMilestoneStatus => {
  if (milestone.is_completed) return "completed";
  if (milestone.completed_issues + milestone.cancelled_issues > 0) return "in_progress";
  return "not_started";
};

export const MILESTONE_STATUS_LABEL: Record<TMilestoneStatus, string> = {
  completed: "Completed",
  in_progress: "In progress",
  not_started: "Not started",
};

export const getMilestoneProgress = (milestone: TMilestone) => {
  if (milestone.total_issues === 0) return 0;
  return Math.round(((milestone.completed_issues + milestone.cancelled_issues) / milestone.total_issues) * 100);
};
