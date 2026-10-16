/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { ChevronDownOutline, ChevronRightOutline } from "@makeplane/propel/icons";
import { PriorityIcon, StateGroupIcon } from "@plane/blocks/icons";
import type { ICycle, TIssuePriorities } from "@plane/types";
import { cn, getFileURL, renderFormattedDate } from "@plane/utils";
// components
import { WorkItemTypeIcon } from "@/components/issues/work-item-type-icon";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useProjectWorkItemTypes } from "@/hooks/use-project-milestones";
// services
import type { TSprintBoardItem } from "@/services/sprint-board.service";
import { SprintBoardService } from "@/services/sprint-board.service";
// local
import type { TSprintFeatureGroup } from "./sprint-scope-data";
import { buildSprintScope, isItemOverdue } from "./sprint-scope-data";

const sprintBoardService = new SprintBoardService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  cycle: ICycle;
};

function ProgressBar({ done, total }: { done: number; total: number }) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-layer-3" aria-hidden="true">
        <div className="h-full rounded-full bg-success-primary" style={{ width: `${percent}%` }} />
      </div>
      <span className="text-caption-sm-medium whitespace-nowrap text-tertiary">
        {done}/{total}
      </span>
    </div>
  );
}

const daysLeft = (endDate: string | null | undefined) => {
  if (!endDate) return null;
  const end = new Date(`${endDate.slice(0, 10)}T23:59:59`);
  return Math.ceil((end.getTime() - Date.now()) / (24 * 60 * 60 * 1000));
};

/**
 * Jira style sprint scope: what the sprint contains by type, every feature with its tasks and progress, and the
 * workload per person. Clicking a work item opens it in the side panel.
 */
export const ActiveSprintScope = observer(function ActiveSprintScope(props: Props) {
  const { workspaceSlug, projectId, cycle } = props;
  // store hooks
  const { getStateById } = useProjectState();
  const { getUserDetails } = useMember();
  const { getProjectIdentifierById } = useProject();
  const { peekIssue, setPeekIssue } = useIssueDetail();
  const { getTypeById } = useProjectWorkItemTypes(workspaceSlug, projectId);
  // ui state
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [assigneeFilter, setAssigneeFilter] = useState<string | null | undefined>(undefined);
  const [hideDone, setHideDone] = useState(false);

  const { data: items, mutate } = useSWR(
    workspaceSlug && projectId && cycle.id ? `SPRINT_BOARD_${cycle.id}` : null,
    () => sprintBoardService.getSprintBoard(workspaceSlug, projectId, cycle.id),
    { refreshInterval: 60_000 }
  );
  // changes made in the side panel show up when it is closed
  const peekedIssueId = peekIssue?.issueId;
  useEffect(() => {
    if (!peekedIssueId) void mutate();
  }, [peekedIssueId, mutate]);

  const isDone = (stateId: string | null) => {
    const group = stateId ? getStateById(stateId)?.group : undefined;
    return group === "completed" || group === "cancelled";
  };
  const scope = useMemo(
    () =>
      buildSprintScope(items ?? [], {
        getTypeKey: (typeId) => (typeId ? getTypeById(typeId)?.key : undefined),
        isDone,
      }),
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- isDone reads the observable state store
    [items, getTypeById, getStateById]
  );
  const identifier = getProjectIdentifierById(projectId);
  const remaining = daysLeft(cycle.end_date);

  if (!items) return null;

  const matchesFilters = (item: TSprintBoardItem) => {
    if (hideDone && isDone(item.state_id)) return false;
    if (assigneeFilter === undefined) return true;
    if (assigneeFilter === null) return item.assignee_ids.length === 0;
    return item.assignee_ids.includes(assigneeFilter);
  };
  const toggleGroup = (key: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const openPeek = (issueId: string) => setPeekIssue({ workspaceSlug, projectId, issueId });

  const renderRow = (item: TSprintBoardItem, depth: number) => {
    const type = item.type_id ? getTypeById(item.type_id) : undefined;
    const state = item.state_id ? getStateById(item.state_id) : undefined;
    const done = isDone(item.state_id);
    const overdue = isItemOverdue(item, done);
    const assignees = item.assignee_ids.map((id) => getUserDetails(id)).filter((user) => !!user);
    return (
      <button
        key={item.id}
        type="button"
        onClick={() => openPeek(item.id)}
        className={cn(
          "grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-subtle py-2 pr-3 text-left text-body-xs-regular hover:bg-layer-transparent-hover md:grid-cols-[minmax(0,1fr)_9rem_5rem_6.5rem_8rem]",
          { "bg-layer-transparent-active": peekIssue?.issueId === item.id }
        )}
        style={{ paddingLeft: 12 + depth * 24 }}
      >
        <span className="flex min-w-0 items-center gap-2">
          {type && <WorkItemTypeIcon type={type} size="xs" />}
          <span className="shrink-0 text-caption-md-medium text-tertiary">
            {identifier}-{item.sequence_id}
          </span>
          <span className={cn("truncate text-primary", { "text-tertiary line-through": done })}>{item.name}</span>
        </span>
        <span className="hidden min-w-0 items-center gap-1.5 md:flex">
          <StateGroupIcon stateGroup={state?.group ?? "backlog"} color={state?.color} className="size-3.5 shrink-0" />
          <span className="truncate text-secondary">{state?.name ?? "—"}</span>
        </span>
        <span className="hidden md:flex" title={item.priority ?? "none"}>
          <PriorityIcon priority={(item.priority ?? "none") as TIssuePriorities} className="size-3.5" />
        </span>
        <span className={cn("hidden truncate md:block", overdue ? "text-danger-primary" : "text-secondary")}>
          {item.target_date ? renderFormattedDate(item.target_date) : "—"}
        </span>
        <span className="flex min-w-0 items-center justify-end gap-1.5 md:justify-start">
          {assignees[0] ? (
            <>
              <Avatar
                alt={assignees[0].display_name}
                fallback={assignees[0].display_name?.[0]?.toUpperCase()}
                src={getFileURL(assignees[0].avatar_url)}
                size="sm"
              />
              <span className="hidden truncate text-secondary md:inline">{assignees[0].display_name}</span>
              {assignees.length > 1 && (
                <span className="text-caption-sm-regular text-tertiary">+{assignees.length - 1}</span>
              )}
            </>
          ) : (
            <span className="text-placeholder">Unassigned</span>
          )}
        </span>
      </button>
    );
  };

  const renderGroup = (group: TSprintFeatureGroup) => {
    const key = group.feature?.id ?? "none";
    const visibleItems = group.items.filter(matchesFilters);
    const featureVisible = group.feature ? matchesFilters(group.feature) : false;
    if (visibleItems.length === 0 && !featureVisible && (assigneeFilter !== undefined || hideDone)) return null;
    const open = !collapsed.has(key);
    const feature = group.feature;
    const featureState = feature?.state_id ? getStateById(feature.state_id) : undefined;
    return (
      <div key={key} className="border-b border-subtle last:border-b-0">
        <div className="flex items-center gap-2 bg-layer-1 py-2 pr-3 pl-2">
          <button
            type="button"
            aria-label={open ? "Collapse" : "Expand"}
            aria-expanded={open}
            className="grid size-6 shrink-0 place-items-center rounded-sm hover:bg-layer-2"
            onClick={() => toggleGroup(key)}
          >
            {open ? <ChevronDownOutline className="size-3.5" /> : <ChevronRightOutline className="size-3.5" />}
          </button>
          {feature ? (
            <button
              type="button"
              onClick={() => openPeek(feature.id)}
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
            >
              {feature.type_id && getTypeById(feature.type_id) && (
                <WorkItemTypeIcon type={getTypeById(feature.type_id)!} size="xs" />
              )}
              <span className="shrink-0 text-caption-md-medium text-tertiary">
                {identifier}-{feature.sequence_id}
              </span>
              <span className="truncate text-body-xs-medium text-primary">{feature.name}</span>
              {!feature.in_sprint && (
                <span className="shrink-0 rounded-sm bg-layer-3 px-1.5 text-caption-sm-regular text-tertiary">
                  not in sprint
                </span>
              )}
              {featureState && (
                <span className="hidden shrink-0 items-center gap-1 text-caption-md-regular text-secondary sm:flex">
                  <StateGroupIcon stateGroup={featureState.group} color={featureState.color} className="size-3" />
                  {featureState.name}
                </span>
              )}
            </button>
          ) : (
            <span className="flex-1 text-body-xs-medium text-secondary">Not under a feature</span>
          )}
          {group.items.length > 0 && <ProgressBar done={group.done} total={group.items.length} />}
        </div>
        {open && visibleItems.map((item) => renderRow(item, 1))}
        {open && group.items.length === 0 && (
          <p className="border-t border-subtle py-2 pl-12 text-caption-md-regular text-tertiary">
            No tasks of this feature are in the sprint.
          </p>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-subtle bg-surface-1 px-3.5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-14 font-semibold text-tertiary">Sprint scope</h3>
          {cycle.description ? (
            <p className="mt-1 max-w-3xl text-body-xs-regular text-secondary">
              <span className="font-medium text-primary">Sprint goal: </span>
              {cycle.description}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-caption-md-medium">
          {remaining !== null && (
            <span className="rounded-md bg-layer-2 px-2 py-1 text-secondary">
              {remaining > 0 ? `${remaining} ${remaining === 1 ? "day" : "days"} left` : "Ends today"}
            </span>
          )}
          <span className="rounded-md bg-layer-2 px-2 py-1 text-secondary">
            {scope.done}/{scope.total} done
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {scope.typeCounts.map((count) => (
          <div key={count.key} className="rounded-md border border-subtle px-3 py-2">
            <p className="text-caption-md-regular text-tertiary">{count.label}</p>
            <p className="text-body-sm-medium text-primary">
              {count.done}/{count.total} <span className="text-caption-md-regular text-tertiary">done</span>
            </p>
          </div>
        ))}
        <div className="rounded-md border border-subtle px-3 py-2">
          <p className="text-caption-md-regular text-tertiary">Overdue</p>
          <p className={cn("text-body-sm-medium", scope.overdue ? "text-danger-primary" : "text-primary")}>
            {scope.overdue}
          </p>
        </div>
        <div className="rounded-md border border-subtle px-3 py-2">
          <p className="text-caption-md-regular text-tertiary">Unassigned</p>
          <p className={cn("text-body-sm-medium", scope.unassigned ? "text-warning-primary" : "text-primary")}>
            {scope.unassigned}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-body-xs-medium text-secondary">Features and tasks</h4>
            <label className="flex items-center gap-1.5 text-caption-md-regular text-secondary">
              <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} />
              Hide done
            </label>
          </div>
          {scope.total === 0 ? (
            <p className="rounded-md border border-subtle px-3 py-6 text-center text-body-xs-regular text-tertiary">
              No work items in this sprint yet. Add features or tasks to the sprint; the tasks under a feature come with
              it.
            </p>
          ) : (
            <div className="overflow-hidden rounded-md border border-subtle">{scope.groups.map(renderGroup)}</div>
          )}
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-body-xs-medium text-secondary">Workload</h4>
            {assigneeFilter !== undefined && (
              <button
                type="button"
                className="text-caption-md-medium text-accent-primary"
                onClick={() => setAssigneeFilter(undefined)}
              >
                Show everyone
              </button>
            )}
          </div>
          <div className="overflow-hidden rounded-md border border-subtle">
            {scope.workload.length === 0 && (
              <p className="px-3 py-4 text-caption-md-regular text-tertiary">Nobody has work in this sprint yet.</p>
            )}
            {scope.workload.map((row) => {
              const user = row.userId ? getUserDetails(row.userId) : undefined;
              const selected = assigneeFilter === row.userId;
              return (
                <button
                  key={row.userId ?? "unassigned"}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setAssigneeFilter(selected ? undefined : row.userId)}
                  className={cn(
                    "flex w-full items-center gap-2 border-b border-subtle px-3 py-2 text-left last:border-b-0 hover:bg-layer-transparent-hover",
                    { "bg-layer-transparent-active": selected }
                  )}
                >
                  {user ? (
                    <Avatar
                      alt={user.display_name}
                      fallback={user.display_name?.[0]?.toUpperCase()}
                      src={getFileURL(user.avatar_url)}
                      size="sm"
                    />
                  ) : (
                    <span className="grid size-5 place-items-center rounded-full bg-layer-3 text-caption-sm-medium text-tertiary">
                      ?
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-body-xs-regular text-primary">
                    {user?.display_name ?? "Unassigned"}
                  </span>
                  <span className="text-caption-sm-regular whitespace-nowrap text-tertiary">
                    {row.total - row.done} open
                  </span>
                  <ProgressBar done={row.done} total={row.total} />
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
});
