/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { Button } from "@makeplane/propel/components/button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import {
  ChevronDownOutline,
  ChevronRightOutline,
  MilestoneOutline,
  ModuleOutline,
  SearchOutline,
} from "@makeplane/propel/icons";
import { PriorityIcon, StateGroupIcon } from "@plane/blocks/icons";
import type { TIssue } from "@plane/types";
import { cn, getFileURL, renderFormattedDate } from "@plane/utils";
// components
import { WorkItemTypeIcon } from "@/components/issues/work-item-type-icon";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useModule } from "@/hooks/store/use-module";
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { projectMilestoneService, useProjectMilestones, useProjectWorkItemTypes } from "@/hooks/use-project-milestones";
import { store } from "@/lib/store-context";
// local imports
import type { TTreeGroupNode, TTreeItemNode } from "./tree";
import { buildMilestoneTree, buildModuleTree, collectExpandableKeys, collectGroupKeys } from "./tree";

export type THierarchyGroupBy = "module" | "milestone";

export const PROJECT_WORK_ITEM_TREE = (projectId: string) => `PROJECT_WORK_ITEM_TREE_${projectId}`;

type Props = {
  workspaceSlug: string;
  projectId: string;
  /** Fixed grouping (e.g. the Milestones page); otherwise the viewer can switch between Module and Milestone. */
  groupBy?: THierarchyGroupBy;
};

// Type | Key | Summary | Status | Priority | Due date | Assignee
const GRID = "grid grid-cols-[minmax(96px,150px)_minmax(92px,110px)_minmax(220px,1fr)_150px_80px_110px_180px]";

const isDone = (issue: TIssue, getStateGroup: (stateId: string | null) => string | undefined) => {
  const group = getStateGroup(issue.state_id);
  return group === "completed" || group === "cancelled";
};

const toggle = (setter: Dispatch<SetStateAction<Set<string>>>, key: string) =>
  setter((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });

/** Jira-style tree of the project: Module -> Feature -> Task, or Milestone -> Module -> Feature -> Task. */
export const WorkItemHierarchyTable = observer(function WorkItemHierarchyTable(props: Props) {
  const { workspaceSlug, projectId, groupBy: fixedGroupBy } = props;
  // states
  const [groupBy, setGroupBy] = useState<THierarchyGroupBy>(fixedGroupBy ?? "module");
  const [search, setSearch] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());
  // store hooks
  const { getProjectById, getProjectIdentifierById } = useProject();
  const { getProjectModuleIds, getModuleById, fetchModules } = useModule();
  const { getStateById } = useProjectState();
  const { getUserDetails } = useMember();
  const { getTypeById } = useProjectWorkItemTypes(workspaceSlug, projectId);
  const { peekIssue, setPeekIssue } = useIssueDetail();
  const isFixedCost = getProjectById(projectId)?.project_type === "fixed_cost";
  const { milestones } = useProjectMilestones(workspaceSlug, isFixedCost ? projectId : undefined);
  const projectIdentifier = getProjectIdentifierById(projectId);
  // every work item of the project, kept in the shared work item store so edits in the peek view show here
  const { data: treeIssues, isLoading } = useSWR(PROJECT_WORK_ITEM_TREE(projectId), () =>
    projectMilestoneService.getWorkItemTree(workspaceSlug, projectId)
  );
  useSWR(`PROJECT_MODULES_FOR_HIERARCHY_${projectId}`, () => fetchModules(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });
  useEffect(() => {
    if (treeIssues?.length) store.issue.issues.addIssue(treeIssues);
  }, [treeIssues]);

  // derived values
  const issues = (treeIssues ?? [])
    .map((issue) => store.issue.issues.getIssueById(issue.id) ?? issue)
    .filter((issue) => !issue.archived_at && !issue.is_draft);
  const issueById = new Map(issues.map((issue) => [issue.id, issue]));
  // modules in their configured order (SOW order for imported projects)
  // copy is sorted, the source array is left untouched (toSorted needs ES2023)
  // oxlint-disable-next-line unicorn/no-array-sort
  const moduleIds = [...(getProjectModuleIds(projectId) ?? [])].sort(
    (a, b) => (getModuleById(a)?.sort_order ?? 0) - (getModuleById(b)?.sort_order ?? 0)
  );
  const getStateGroup = (stateId: string | null) => (stateId ? getStateById(stateId)?.group : undefined);
  const searchTerm = search.trim().toLowerCase();
  const matches = (issue: TIssue) =>
    !searchTerm ||
    issue.name.toLowerCase().includes(searchTerm) ||
    `${projectIdentifier}-${issue.sequence_id}`.toLowerCase().includes(searchTerm);
  const members = issues.filter(matches);
  // ancestors are looked up from all work items so a matching task still shows under its feature
  const groups: TTreeGroupNode[] = (() => {
    const withAncestors = [...members, ...issues.filter((issue) => !matches(issue))];
    const memberIds = new Set(members.map((issue) => issue.id));
    const tree =
      groupBy === "milestone"
        ? buildMilestoneTree(
            withAncestors,
            (milestones ?? []).map((m) => ({ id: m.id })),
            moduleIds.map((id) => ({ id }))
          )
        : buildModuleTree(
            withAncestors,
            moduleIds.map((id) => ({ id }))
          );
    if (!searchTerm) return tree;
    // keep only branches that contain a match
    const prune = (nodes: TTreeItemNode[]): TTreeItemNode[] =>
      nodes
        .map((node) => ({ ...node, children: prune(node.children), isContext: !memberIds.has(node.issueId) }))
        .filter((node) => !node.isContext || node.children.length > 0);
    const pruneGroups = (items: TTreeGroupNode[]): TTreeGroupNode[] =>
      items
        .map((group) => ({
          ...group,
          items: prune(group.items),
          subGroups: pruneGroups(group.subGroups),
          issueIds: group.issueIds.filter((id) => memberIds.has(id)),
        }))
        .filter((group) => group.items.length > 0 || group.subGroups.length > 0);
    return pruneGroups(tree);
  })();

  const isGroupOpen = (key: string) => !collapsedGroups.has(key);
  const isItemOpen = (key: string) => !!searchTerm || expandedItems.has(key);

  const openPeek = (issueId: string) => setPeekIssue({ workspaceSlug, projectId, issueId });

  const renderGroupLabel = (group: TTreeGroupNode) => {
    if (group.kind === "milestone") {
      const milestone = milestones?.find((item) => item.id === group.id);
      return (
        <>
          <MilestoneOutline className="size-4 shrink-0 text-tertiary" />
          <span className="truncate text-body-xs-medium text-primary">
            {milestone ? (milestone.code ? `${milestone.code} · ${milestone.name}` : milestone.name) : "No milestone"}
          </span>
        </>
      );
    }
    const module = group.id ? getModuleById(group.id) : undefined;
    return (
      <>
        <ModuleOutline className="size-4 shrink-0 text-tertiary" />
        <span className="truncate text-body-xs-medium text-primary">{module?.name ?? "No module"}</span>
      </>
    );
  };

  const renderGroup = (group: TTreeGroupNode, depth: number) => {
    const open = isGroupOpen(group.key);
    const groupIssues = group.issueIds.map((id) => issueById.get(id)).filter((issue): issue is TIssue => !!issue);
    const done = groupIssues.filter((issue) => isDone(issue, getStateGroup)).length;
    const progress = groupIssues.length ? Math.round((done / groupIssues.length) * 100) : 0;
    return (
      <Fragment key={group.key}>
        <div
          role="row"
          className={cn(
            "flex items-center gap-2 border-b border-subtle px-3 py-2",
            depth === 0 ? "bg-layer-1" : "bg-surface-1"
          )}
          style={{ paddingLeft: 12 + depth * 20 }}
        >
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
            aria-expanded={open}
            onClick={() => toggle(setCollapsedGroups, group.key)}
          >
            {open ? (
              <ChevronDownOutline className="size-3.5 shrink-0 text-secondary" />
            ) : (
              <ChevronRightOutline className="size-3.5 shrink-0 text-secondary" />
            )}
            {renderGroupLabel(group)}
            <span className="shrink-0 rounded-sm bg-layer-2 px-1.5 text-caption-sm-medium text-secondary">
              {groupIssues.length}
            </span>
          </button>
          <div className="flex shrink-0 items-center gap-2">
            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-layer-3">
              <div
                className={cn("h-full rounded-full", progress === 100 ? "bg-success-primary" : "bg-accent-primary")}
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-24 text-right text-caption-sm-regular whitespace-nowrap text-tertiary">
              {done} / {groupIssues.length} done
            </span>
          </div>
        </div>
        {open && (
          <>
            {group.subGroups.map((subGroup) => renderGroup(subGroup, depth + 1))}
            {group.items.map((node) => renderItem(node, group.key, depth + 1))}
          </>
        )}
      </Fragment>
    );
  };

  const renderItem = (node: TTreeItemNode, parentKey: string, depth: number) => {
    const issue = issueById.get(node.issueId);
    if (!issue) return null;
    const key = `${parentKey}/${node.issueId}`;
    const open = isItemOpen(key);
    const type = getTypeById(issue.type_id);
    const state = issue.state_id ? getStateById(issue.state_id) : undefined;
    const assignees = (issue.assignee_ids ?? []).map((id) => getUserDetails(id)).filter((user) => !!user);
    const isPeeked = peekIssue?.issueId === issue.id;
    return (
      <Fragment key={key}>
        <div
          role="row"
          tabIndex={0}
          className={cn(
            GRID,
            "group cursor-pointer items-center border-b border-subtle text-body-xs-regular hover:bg-layer-transparent-hover",
            { "bg-layer-transparent-active": isPeeked, "opacity-60": node.isContext }
          )}
          onClick={() => openPeek(issue.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter") openPeek(issue.id);
            if (e.key === "ArrowRight" && node.children.length && !open) toggle(setExpandedItems, key);
            if (e.key === "ArrowLeft" && open) toggle(setExpandedItems, key);
          }}
        >
          <div className="flex items-center gap-1 py-2" style={{ paddingLeft: 12 + depth * 20 }}>
            {node.children.length > 0 ? (
              <button
                type="button"
                aria-label={open ? `Collapse ${issue.name}` : `Expand ${issue.name}`}
                aria-expanded={open}
                className="grid size-5 shrink-0 place-items-center rounded-sm hover:bg-layer-2"
                onClick={(e) => {
                  e.stopPropagation();
                  toggle(setExpandedItems, key);
                }}
              >
                {open ? <ChevronDownOutline className="size-3.5" /> : <ChevronRightOutline className="size-3.5" />}
              </button>
            ) : (
              <span className="size-5 shrink-0" />
            )}
            {type && <WorkItemTypeIcon type={type} />}
            {node.children.length > 0 && (
              <span className="text-caption-sm-regular text-tertiary">{node.children.length}</span>
            )}
          </div>
          <div className="truncate pr-2 text-caption-md-medium text-secondary">
            {projectIdentifier}-{issue.sequence_id}
          </div>
          <div className="truncate pr-3 text-primary" title={issue.name}>
            {issue.name}
          </div>
          <div className="flex min-w-0 items-center gap-1.5 pr-2">
            <StateGroupIcon stateGroup={state?.group ?? "backlog"} color={state?.color} className="size-3.5 shrink-0" />
            <span className="truncate text-secondary">{state?.name ?? "—"}</span>
          </div>
          <div className="flex items-center gap-1 pr-2 text-secondary" title={issue.priority ?? "none"}>
            <PriorityIcon priority={issue.priority ?? "none"} className="size-3.5" />
          </div>
          <div className="truncate pr-2 text-secondary">
            {issue.target_date ? renderFormattedDate(issue.target_date) : "—"}
          </div>
          <div className="flex min-w-0 items-center gap-1.5 pr-3">
            {assignees[0] ? (
              <>
                <Avatar
                  alt={assignees[0].display_name}
                  fallback={assignees[0].display_name?.[0]?.toUpperCase()}
                  src={getFileURL(assignees[0].avatar_url)}
                  size="sm"
                />
                <span className="truncate text-secondary">{assignees[0].display_name}</span>
                {assignees.length > 1 && (
                  <span className="shrink-0 text-caption-sm-regular text-tertiary">+{assignees.length - 1}</span>
                )}
              </>
            ) : (
              <span className="text-placeholder">Unassigned</span>
            )}
          </div>
        </div>
        {open && node.children.map((child) => renderItem(child, key, depth + 1))}
      </Fragment>
    );
  };

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-subtle px-page-x py-2.5">
        <div className="w-60">
          <InputGroup size="md">
            <SearchOutline className="ml-2 size-3.5 shrink-0 text-tertiary" />
            <Input
              size="md"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search work items"
              aria-label="Search work items"
            />
          </InputGroup>
        </div>
        {!fixedGroupBy && isFixedCost && (
          <div className="flex items-center gap-1 rounded-md bg-layer-3 p-1" role="group" aria-label="Group by">
            {(["module", "milestone"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={groupBy === option}
                onClick={() => setGroupBy(option)}
                className={cn(
                  "rounded-sm px-2 py-0.5 text-caption-md-medium text-secondary hover:bg-layer-transparent-hover",
                  { "bg-layer-transparent-active text-primary": groupBy === option }
                )}
              >
                {option === "module" ? "By module" : "By milestone"}
              </button>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            stretch="auto"
            label="Expand all"
            onClick={() => {
              setCollapsedGroups(new Set());
              setExpandedItems(new Set(collectExpandableKeys(groups)));
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            stretch="auto"
            label="Collapse all"
            onClick={() => {
              setExpandedItems(new Set());
              setCollapsedGroups(new Set(collectGroupKeys(groups)));
            }}
          />
        </div>
      </div>
      <div className="vertical-scrollbar horizontal-scrollbar scrollbar-md min-h-0 flex-1 overflow-auto">
        <div role="table" aria-label="Work item hierarchy" className="min-w-[960px]">
          <div
            role="row"
            className={cn(
              GRID,
              "sticky top-0 z-10 border-b border-subtle bg-surface-1 py-2 text-caption-sm-medium text-tertiary"
            )}
          >
            <span className="pl-3">Type</span>
            <span>Key</span>
            <span>Summary</span>
            <span>Status</span>
            <span>Priority</span>
            <span>Due date</span>
            <span>Assignee</span>
          </div>
          {isLoading && !treeIssues ? (
            <div className="px-page-x py-6 text-body-xs-regular text-tertiary">Loading work items…</div>
          ) : groups.length === 0 ? (
            <div className="px-page-x py-6 text-body-xs-regular text-tertiary">
              {searchTerm ? "No work items match your search." : "No work items yet."}
            </div>
          ) : (
            groups.map((group) => renderGroup(group, 0))
          )}
        </div>
      </div>
    </div>
  );
});
