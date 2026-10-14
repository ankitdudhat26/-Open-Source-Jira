/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssue } from "@plane/types";

/** A work item in the tree. `isContext` marks an ancestor shown only to place matching children (e.g. a feature
 * from another milestone whose task is delivered in this one). */
export type TTreeItemNode = {
  issueId: string;
  isContext: boolean;
  children: TTreeItemNode[];
};

export type TTreeGroupKind = "milestone" | "module";

/** A milestone or module row; holds either sub groups (milestone -> modules) or work items. */
export type TTreeGroupNode = {
  key: string;
  kind: TTreeGroupKind;
  // id of the milestone / module, null for "No module" / "No milestone"
  id: string | null;
  subGroups: TTreeGroupNode[];
  items: TTreeItemNode[];
  // work items in the group (ancestors shown for context are not counted)
  issueIds: string[];
};

type TGroupDefinition = { id: string };

// copy is sorted, the source array is left untouched (toSorted needs ES2023)
// oxlint-disable-next-line unicorn/no-array-sort
const bySequence = (issues: TIssue[]) => [...issues].sort((a, b) => a.sequence_id - b.sequence_id);

/**
 * Work items of one group arranged under their parents. Every member is shown under its parent chain;
 * ancestors that are not members themselves are included as context so the hierarchy stays readable.
 */
export const buildItemForest = (members: TIssue[], issueMap: Map<string, TIssue>): TTreeItemNode[] => {
  const memberIds = new Set(members.map((issue) => issue.id));
  // members plus all of their ancestors
  const included = new Set<string>();
  for (const issue of members) {
    let current: TIssue | undefined = issue;
    const seen = new Set<string>();
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      included.add(current.id);
      current = current.parent_id ? issueMap.get(current.parent_id) : undefined;
    }
  }

  const childrenOf = new Map<string, TIssue[]>();
  const roots: TIssue[] = [];
  for (const issueId of included) {
    const issue = issueMap.get(issueId);
    if (!issue) continue;
    if (issue.parent_id && included.has(issue.parent_id)) {
      const siblings = childrenOf.get(issue.parent_id) ?? [];
      siblings.push(issue);
      childrenOf.set(issue.parent_id, siblings);
    } else roots.push(issue);
  }

  const toNode = (issue: TIssue, path: Set<string>): TTreeItemNode => {
    const nextPath = new Set(path).add(issue.id);
    return {
      issueId: issue.id,
      isContext: !memberIds.has(issue.id),
      children: bySequence(childrenOf.get(issue.id) ?? [])
        .filter((child) => !nextPath.has(child.id))
        .map((child) => toNode(child, nextPath)),
    };
  };
  return bySequence(roots).map((issue) => toNode(issue, new Set()));
};

const buildModuleGroups = (
  members: TIssue[],
  modules: TGroupDefinition[],
  issueMap: Map<string, TIssue>,
  keyPrefix: string
): TTreeGroupNode[] => {
  const groups: TTreeGroupNode[] = [];
  for (const module of modules) {
    const moduleMembers = members.filter((issue) => issue.module_ids?.includes(module.id));
    if (moduleMembers.length === 0) continue;
    groups.push({
      key: `${keyPrefix}module:${module.id}`,
      kind: "module",
      id: module.id,
      subGroups: [],
      items: buildItemForest(moduleMembers, issueMap),
      issueIds: moduleMembers.map((issue) => issue.id),
    });
  }
  const moduleIds = new Set(modules.map((module) => module.id));
  const withoutModule = members.filter((issue) => !issue.module_ids?.some((id) => moduleIds.has(id)));
  if (withoutModule.length > 0)
    groups.push({
      key: `${keyPrefix}module:none`,
      kind: "module",
      id: null,
      subGroups: [],
      items: buildItemForest(withoutModule, issueMap),
      issueIds: withoutModule.map((issue) => issue.id),
    });
  return groups;
};

/** Module -> work items (features with their tasks). */
export const buildModuleTree = (issues: TIssue[], modules: TGroupDefinition[]): TTreeGroupNode[] => {
  const issueMap = new Map(issues.map((issue) => [issue.id, issue]));
  return buildModuleGroups(issues, modules, issueMap, "");
};

/** Milestone -> module -> work items. A work item belongs to the milestone it is tagged with. */
export const buildMilestoneTree = (
  issues: TIssue[],
  milestones: TGroupDefinition[],
  modules: TGroupDefinition[]
): TTreeGroupNode[] => {
  const issueMap = new Map(issues.map((issue) => [issue.id, issue]));
  const groups: TTreeGroupNode[] = [];
  const milestoneIds = new Set(milestones.map((milestone) => milestone.id));
  for (const milestone of [...milestones, { id: null as string | null }]) {
    const members =
      milestone.id === null
        ? issues.filter((issue) => !issue.milestone_id || !milestoneIds.has(issue.milestone_id))
        : issues.filter((issue) => issue.milestone_id === milestone.id);
    if (members.length === 0) continue;
    const key = `milestone:${milestone.id ?? "none"}`;
    groups.push({
      key,
      kind: "milestone",
      id: milestone.id,
      subGroups: buildModuleGroups(members, modules, issueMap, `${key}/`),
      items: [],
      issueIds: members.map((issue) => issue.id),
    });
  }
  return groups;
};

/** Keys of all work item rows that have children, for "Expand all". */
export const collectExpandableKeys = (groups: TTreeGroupNode[]): string[] => {
  const keys: string[] = [];
  const walk = (nodes: TTreeItemNode[], prefix: string) => {
    for (const node of nodes) {
      const key = `${prefix}/${node.issueId}`;
      if (node.children.length > 0) keys.push(key);
      walk(node.children, key);
    }
  };
  const walkGroups = (items: TTreeGroupNode[]) => {
    for (const group of items) {
      walk(group.items, group.key);
      walkGroups(group.subGroups);
    }
  };
  walkGroups(groups);
  return keys;
};

/** Keys of all group rows, for "Collapse all". */
export const collectGroupKeys = (groups: TTreeGroupNode[]): string[] =>
  groups.flatMap((group) => [group.key, ...collectGroupKeys(group.subGroups)]);
