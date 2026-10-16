/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TWorkItemTypeKey } from "@plane/types";
import type { TSprintBoardItem } from "@/services/sprint-board.service";

export type TSprintTypeKey = TWorkItemTypeKey;

export type TSprintFeatureGroup = {
  /** null: the sprint's work items that are not under a feature */
  feature: TSprintBoardItem | null;
  items: TSprintBoardItem[];
  done: number;
};

export type TSprintTypeCount = { key: TSprintTypeKey; label: string; total: number; done: number };

export type TSprintWorkload = { userId: string | null; total: number; done: number };

export type TSprintScope = {
  groups: TSprintFeatureGroup[];
  typeCounts: TSprintTypeCount[];
  workload: TSprintWorkload[];
  overdue: number;
  unassigned: number;
  total: number;
  done: number;
};

type Lookups = {
  getTypeKey: (typeId: string | null) => TSprintTypeKey | undefined;
  isDone: (stateId: string | null) => boolean;
  today?: Date;
};

const TYPE_LABELS: Record<TSprintTypeKey, string> = { feature: "Features", task: "Tasks", bug: "Bugs" };

const isOverdue = (item: TSprintBoardItem, done: boolean, today: Date) => {
  if (done || !item.target_date) return false;
  const due = new Date(`${item.target_date.slice(0, 10)}T23:59:59`);
  return due < today;
};

/**
 * Shape the sprint's work items like Jira's sprint view: features with the sprint's tasks under them,
 * counts per work item type, and the workload per person.
 */
export const buildSprintScope = (items: TSprintBoardItem[], lookups: Lookups): TSprintScope => {
  const { getTypeKey, isDone } = lookups;
  const today = lookups.today ?? new Date();
  const byId = new Map(items.map((item) => [item.id, item]));
  const typeOf = (item: TSprintBoardItem): TSprintTypeKey => getTypeKey(item.type_id) ?? "task";
  const sprintItems = items.filter((item) => item.in_sprint);

  // nearest feature above a work item (itself when it is a feature)
  const featureOf = (item: TSprintBoardItem): TSprintBoardItem | null => {
    const seen = new Set<string>();
    let current: TSprintBoardItem | undefined = item.parent_id ? byId.get(item.parent_id) : undefined;
    while (current && !seen.has(current.id)) {
      if (typeOf(current) === "feature") return current;
      seen.add(current.id);
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    return null;
  };

  const groupMap = new Map<string, TSprintFeatureGroup>();
  const ungrouped: TSprintFeatureGroup = { feature: null, items: [], done: 0 };
  // features in the sprint get a group even without tasks
  for (const item of sprintItems) {
    if (typeOf(item) === "feature") groupMap.set(item.id, { feature: item, items: [], done: 0 });
  }
  for (const item of sprintItems) {
    if (typeOf(item) === "feature") continue;
    const feature = featureOf(item);
    let group = ungrouped;
    if (feature) {
      group = groupMap.get(feature.id) ?? { feature, items: [], done: 0 };
      groupMap.set(feature.id, group);
    }
    group.items.push(item);
    if (isDone(item.state_id)) group.done += 1;
  }
  // spread copies are sorted, toSorted needs ES2023
  // oxlint-disable-next-line unicorn/no-array-sort
  const groups = [...groupMap.values()].sort((a, b) => (a.feature?.sequence_id ?? 0) - (b.feature?.sequence_id ?? 0));
  if (ungrouped.items.length > 0) groups.push(ungrouped);

  const typeCounts = (Object.keys(TYPE_LABELS) as TSprintTypeKey[]).map((key) => {
    const ofType = sprintItems.filter((item) => typeOf(item) === key);
    return {
      key,
      label: TYPE_LABELS[key],
      total: ofType.length,
      done: ofType.filter((item) => isDone(item.state_id)).length,
    };
  });

  const workloadMap = new Map<string | null, TSprintWorkload>();
  let overdue = 0;
  let unassigned = 0;
  for (const item of sprintItems) {
    const done = isDone(item.state_id);
    if (isOverdue(item, done, today)) overdue += 1;
    if (item.assignee_ids.length === 0 && !done) unassigned += 1;
    const owners = item.assignee_ids.length > 0 ? item.assignee_ids : [null];
    for (const owner of owners) {
      const row = workloadMap.get(owner) ?? { userId: owner, total: 0, done: 0 };
      row.total += 1;
      if (done) row.done += 1;
      workloadMap.set(owner, row);
    }
  }
  // spread copies are sorted, toSorted needs ES2023
  // oxlint-disable-next-line unicorn/no-array-sort
  const workload = [...workloadMap.values()].sort((a, b) => b.total - b.done - (a.total - a.done) || b.total - a.total);

  return {
    groups,
    typeCounts,
    workload,
    overdue,
    unassigned,
    total: sprintItems.length,
    done: sprintItems.filter((item) => isDone(item.state_id)).length,
  };
};

export const isItemOverdue = (item: TSprintBoardItem, done: boolean, today = new Date()) =>
  isOverdue(item, done, today);
