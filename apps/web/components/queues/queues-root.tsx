/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { PriorityIcon, StateGroupIcon } from "@plane/blocks/icons";
import type { TIssuePriorities, TStateGroups } from "@plane/types";
import { cn, getFileURL, renderFormattedDate } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { groupQueueService, useWorkspaceQueues } from "@/hooks/use-groups-queues";
// services
import type { TQueueFilter, TQueueIssue } from "@/services/group-queue.service";
// local
import { QueueItemPanel } from "./queue-item-panel";

type Props = { workspaceSlug: string };

const FILTERS: { key: TQueueFilter; label: string; count: "unassigned" | "mine" | "open" | "done" }[] = [
  { key: "unassigned", label: "Unassigned", count: "unassigned" },
  { key: "mine", label: "Assigned to me", count: "mine" },
  { key: "open", label: "All open", count: "open" },
  { key: "done", label: "Done", count: "done" },
];

const isOverdue = (item: TQueueIssue) =>
  !!item.target_date &&
  !["completed", "cancelled"].includes(item.state?.group ?? "") &&
  new Date(`${item.target_date.slice(0, 10)}T23:59:59`) < new Date();

/**
 * Group queues (e.g. DevOps): work items sent from every project. Members of the group see them read only, take
 * one with "Assign to me" and can then change it.
 */
export const QueuesRoot = observer(function QueuesRoot(props: Props) {
  const { workspaceSlug } = props;
  const { getUserDetails } = useMember();
  const { queues, mutate: refreshQueues, isLoading } = useWorkspaceQueues(workspaceSlug);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [filter, setFilter] = useState<TQueueFilter>("unassigned");
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);

  // open the first queue the user belongs to
  useEffect(() => {
    if (!queues?.length || (groupId && queues.some((queue) => queue.group.id === groupId))) return;
    setGroupId((queues.find((queue) => queue.is_member) ?? queues[0]).group.id);
  }, [queues, groupId]);

  const queue = queues?.find((item) => item.group.id === groupId);
  const { data: items, mutate: refreshItems } = useSWR(
    groupId ? `QUEUE_ITEMS_${groupId}_${filter}` : null,
    () => groupQueueService.getQueueItems(workspaceSlug, groupId!, filter),
    { refreshInterval: 60_000 }
  );

  const refreshAll = () => {
    void refreshItems();
    void refreshQueues();
  };

  if (isLoading && !queues) return <div className="p-6 text-body-xs-regular text-tertiary">Loading queues...</div>;
  if (!queues?.length)
    return (
      <div className="mx-auto mt-16 max-w-md px-4 text-center">
        <h2 className="text-h5-medium text-primary">No queues for you yet</h2>
        <p className="mt-2 text-body-xs-regular text-tertiary">
          Queues belong to groups such as DevOps. A workspace admin can add you to a group in Settings → Groups.
        </p>
      </div>
    );

  return (
    <div className="flex h-full w-full overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* queues */}
        <div className="flex flex-wrap items-center gap-2 border-b border-subtle px-page-x py-3">
          {queues.map((item) => (
            <button
              key={item.group.id}
              type="button"
              onClick={() => {
                setGroupId(item.group.id);
                setSelectedIssueId(null);
              }}
              className={cn(
                "flex items-center gap-2 rounded-md border px-3 py-1.5 text-body-xs-medium",
                item.group.id === groupId
                  ? "border-accent-strong bg-accent-subtle text-accent-primary"
                  : "border-subtle text-secondary hover:bg-layer-transparent-hover"
              )}
            >
              <span className="size-2 rounded-full" style={{ backgroundColor: item.group.color }} />
              {item.group.name} queue
              <span className="rounded-sm bg-layer-3 px-1.5 text-caption-sm-medium text-primary">
                {item.counts.open}
              </span>
            </button>
          ))}
        </div>

        {/* filters */}
        {queue && (
          <div className="flex flex-wrap items-center gap-1 border-b border-subtle px-page-x py-2" role="tablist">
            {FILTERS.map((option) => (
              <button
                key={option.key}
                type="button"
                role="tab"
                aria-selected={filter === option.key}
                onClick={() => setFilter(option.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-body-xs-medium",
                  filter === option.key ? "bg-layer-3 text-primary" : "text-tertiary hover:text-secondary"
                )}
              >
                {option.label} <span className="text-tertiary">{queue.counts[option.count]}</span>
              </button>
            ))}
            {!queue.is_member && (
              <span className="ml-auto text-caption-md-regular text-tertiary">
                You see this queue as a workspace admin.
              </span>
            )}
          </div>
        )}

        {/* items */}
        <div className="flex-1 overflow-auto">
          {items && items.length === 0 && (
            <p className="px-page-x py-10 text-center text-body-xs-regular text-tertiary">
              {filter === "unassigned" ? "Nothing waiting in this queue." : "No work items here."}
            </p>
          )}
          {items && items.length > 0 && (
            <table className="w-full min-w-[720px] text-left text-body-xs-regular">
              <thead className="sticky top-0 z-[1] bg-surface-1 text-caption-md-medium text-tertiary">
                <tr className="border-b border-subtle">
                  <th className="px-page-x py-2 font-medium">Project</th>
                  <th className="py-2 pr-3 font-medium">Work item</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Priority</th>
                  <th className="py-2 pr-3 font-medium">Assignee</th>
                  <th className="py-2 pr-3 font-medium">Due</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const assignee = item.assignee_ids[0] ? getUserDetails(item.assignee_ids[0]) : undefined;
                  return (
                    <tr
                      key={item.id}
                      tabIndex={0}
                      onClick={() => setSelectedIssueId(item.id)}
                      onKeyDown={(event) => event.key === "Enter" && setSelectedIssueId(item.id)}
                      className={cn("cursor-pointer border-b border-subtle hover:bg-layer-transparent-hover", {
                        "bg-layer-transparent-active": selectedIssueId === item.id,
                      })}
                    >
                      <td className="px-page-x py-2.5 text-secondary">
                        <span className="block max-w-40 truncate" title={item.project.name}>
                          {item.project.name}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3">
                        <span className="mr-2 text-caption-md-medium text-tertiary">{item.key}</span>
                        <span className="text-primary">{item.name}</span>
                        {item.type && (
                          <span className="ml-2 rounded-sm bg-layer-3 px-1.5 text-caption-sm-regular text-tertiary">
                            {item.type}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        <span className="flex items-center gap-1.5 text-secondary">
                          <StateGroupIcon
                            stateGroup={(item.state?.group ?? "backlog") as TStateGroups}
                            color={item.state?.color}
                            className="size-3.5"
                          />
                          {item.state?.name ?? "—"}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3">
                        <PriorityIcon priority={(item.priority ?? "none") as TIssuePriorities} className="size-3.5" />
                      </td>
                      <td className="py-2.5 pr-3">
                        {assignee ? (
                          <span className="flex items-center gap-1.5 text-secondary">
                            <Avatar
                              alt={assignee.display_name}
                              fallback={assignee.display_name?.[0]?.toUpperCase()}
                              src={getFileURL(assignee.avatar_url)}
                              size="sm"
                            />
                            {item.is_mine ? "You" : assignee.display_name}
                            {item.assignee_ids.length > 1 && (
                              <span className="text-tertiary">+{item.assignee_ids.length - 1}</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-placeholder">Unassigned</span>
                        )}
                      </td>
                      <td className={cn("py-2.5 pr-3", isOverdue(item) ? "text-danger-primary" : "text-secondary")}>
                        {item.target_date ? renderFormattedDate(item.target_date) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {groupId && selectedIssueId && (
        <QueueItemPanel
          workspaceSlug={workspaceSlug}
          groupId={groupId}
          issueId={selectedIssueId}
          onClose={() => setSelectedIssueId(null)}
          onChanged={refreshAll}
        />
      )}
    </div>
  );
});
