/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
import { setToast } from "@plane/blocks/toast";
import { EIssueServiceType } from "@plane/types";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";

type TIssueWatchersSelect = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
  serviceType?: EIssueServiceType;
};

/**
 * Jira style watchers: everyone picked here gets in-app and email notifications for comments and changes
 * on the work item. Adding or removing yourself is the same as Watch / Stop watching in the header.
 */
export const IssueWatchersSelect = observer(function IssueWatchersSelect(props: TIssueWatchersSelect) {
  const { workspaceSlug, projectId, issueId, disabled = false, serviceType = EIssueServiceType.ISSUES } = props;
  // store hooks
  const {
    subscription: { getWatcherIdsByIssueId },
    fetchWatchers,
    addWatchers,
    removeWatcher,
  } = useIssueDetail(serviceType);

  useSWR(
    workspaceSlug && projectId && issueId ? `ISSUE_WATCHERS_${workspaceSlug}_${projectId}_${issueId}` : null,
    workspaceSlug && projectId && issueId ? () => fetchWatchers(workspaceSlug, projectId, issueId) : null,
    { revalidateOnFocus: false }
  );

  const watcherIds = getWatcherIdsByIssueId(issueId) ?? [];

  const handleChange = async (userIds: string[]) => {
    const added = userIds.filter((id) => !watcherIds.includes(id));
    const removed = watcherIds.filter((id) => !userIds.includes(id));
    try {
      await Promise.all([
        addWatchers(workspaceSlug, projectId, issueId, added),
        ...removed.map((userId) => removeWatcher(workspaceSlug, projectId, issueId, userId)),
      ]);
    } catch (error) {
      const message =
        error && typeof error === "object" && "error" in error && typeof error.error === "string"
          ? error.error
          : "Watchers could not be updated. Please try again.";
      setToast({ type: "error", title: "Error!", message });
    }
  };

  return (
    <MemberSelect
      testId="work-item-watchers-select"
      value={watcherIds}
      onChange={(userIds) => void handleChange(userIds)}
      disabled={disabled}
      projectId={projectId}
      placeholder="Add watchers"
      multiple
      variant="select-ghost-md"
      showLabel={watcherIds.length <= 1}
      tooltip={{ heading: "Watchers" }}
    />
  );
});
