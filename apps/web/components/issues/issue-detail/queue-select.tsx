/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { ChevronDownOutline } from "@makeplane/propel/icons";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { groupQueueService, useWorkspaceGroups, useWorkspaceQueues } from "@/hooks/use-groups-queues";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
};

type TOption = { key: string; label: string; color?: string };

const NO_QUEUE: TOption = { key: "", label: "No queue" };

/** Send the work item to a group's queue (e.g. DevOps), move it to another queue or take it out. */
export const IssueQueueSelect = observer(function IssueQueueSelect(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { groups } = useWorkspaceGroups(workspaceSlug);
  const { mutate: refreshQueues } = useWorkspaceQueues(workspaceSlug);
  const { fetchActivities } = useIssueDetail();
  const { data, mutate } = useSWR(`WORK_ITEM_QUEUE_${issueId}`, () =>
    groupQueueService.getWorkItemQueue(workspaceSlug, projectId, issueId)
  );

  const options: TOption[] = [
    NO_QUEUE,
    ...(groups ?? [])
      .filter((group) => group.has_queue)
      .map((group) => ({ key: group.id, label: `${group.name} queue`, color: group.color })),
  ];
  const selected = options.find((option) => option.key === (data?.group_id ?? "")) ?? NO_QUEUE;

  const handleChange = async (key: string) => {
    if (key === (data?.group_id ?? "")) return;
    try {
      const updated = await groupQueueService.setWorkItemQueue(workspaceSlug, projectId, issueId, key || null);
      await mutate(updated, { revalidate: false });
      void refreshQueues();
      void fetchActivities(workspaceSlug, projectId, issueId);
      setToast({
        type: "success",
        title: updated.group_name ? `Sent to the ${updated.group_name} queue` : "Removed from the queue",
        message: updated.group_name ? "Its members can now see and take it." : "",
      });
    } catch (error) {
      const message =
        error && typeof error === "object" && "error" in error && typeof error.error === "string"
          ? error.error
          : "The queue could not be changed.";
      setToast({ type: "error", title: "Error!", message });
    }
  };

  return (
    <Select<TOption>
      getValues={() => options}
      value={selected}
      onChange={(key) => void handleChange(key)}
      getOptionValue={(option) => option.key}
      getOptionLabel={(option) => option.label}
      showSearch={false}
      pinSelected={false}
      disabled={disabled}
    >
      <Select.Trigger<TOption> variant="select-ghost-md" appendIcon={<ChevronDownOutline />}>
        <span className="flex min-w-0 grow items-center gap-1.5 truncate text-left">
          {selected.color && (
            <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: selected.color }} />
          )}
          <span className={selected.key ? "text-primary" : "text-placeholder"}>{selected.label}</span>
        </span>
      </Select.Trigger>
    </Select>
  );
});
