/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useCallback, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { setToast } from "@plane/blocks/toast";
import type { ISearchIssueResponse, TIssue } from "@plane/types";
// components
import { IssueModalContext } from "@/components/issues/issue-modal/context";
import type { TCreateUpdatePropertyValuesProps } from "@/components/issues/issue-modal/context";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useUser } from "@/hooks/store/user/user-user";

export type TIssueModalProviderProps = {
  templateId?: string;
  dataForPreload?: Partial<TIssue>;
  allowedProjectIds?: string[];
  children: React.ReactNode;
};

export const IssueModalProvider = observer(function IssueModalProvider(props: TIssueModalProviderProps) {
  const { children, allowedProjectIds } = props;
  // states
  const [selectedParentIssue, setSelectedParentIssue] = useState<ISearchIssueResponse | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<File[]>([]);
  const [pendingBlockedByIssues, setPendingBlockedByIssues] = useState<ISearchIssueResponse[]>([]);
  // store hooks
  const { projectIdsWithWorkItemCreatePermissions } = useUser();
  const { createAttachment, createRelation } = useIssueDetail();

  // Runs after a work item is created or updated: uploads the attachments and adds the "blocked by" relations
  // that were picked in the create form.
  const handleCreateUpdatePropertyValues = useCallback(
    async ({ workspaceSlug, projectId, issueId, isDraft }: TCreateUpdatePropertyValuesProps) => {
      if (isDraft) return;
      const attachments = pendingAttachments;
      const blockedByIds = pendingBlockedByIssues.map((issue) => issue.id);
      setPendingAttachments([]);
      setPendingBlockedByIssues([]);

      const results = await Promise.allSettled([
        ...attachments.map((file) => createAttachment(workspaceSlug, projectId, issueId, file)),
        ...(blockedByIds.length > 0
          ? [createRelation(workspaceSlug, projectId, issueId, "blocked_by", blockedByIds)]
          : []),
      ]);
      if (results.some((result) => result.status === "rejected"))
        setToast({
          type: "error",
          title: "Error!",
          message: "The work item was created, but some attachments or blocked by work items could not be added.",
        });
    },
    [pendingAttachments, pendingBlockedByIssues, createAttachment, createRelation]
  );

  return (
    <IssueModalContext.Provider
      // oxlint-disable-next-line react/jsx-no-constructed-context-values
      value={{
        allowedProjectIds: allowedProjectIds ?? projectIdsWithWorkItemCreatePermissions,
        workItemTemplateId: null,
        setWorkItemTemplateId: () => {},
        isApplyingTemplate: false,
        setIsApplyingTemplate: () => {},
        selectedParentIssue,
        setSelectedParentIssue,
        issuePropertyValues: {},
        setIssuePropertyValues: () => {},
        issuePropertyValueErrors: {},
        setIssuePropertyValueErrors: () => {},
        getIssueTypeIdOnProjectChange: () => null,
        getActiveAdditionalPropertiesLength: () => 0,
        handlePropertyValuesValidation: () => true,
        handleCreateUpdatePropertyValues,
        handleProjectEntitiesFetch: () => Promise.resolve(),
        handleTemplateChange: () => Promise.resolve(),
        handleConvert: () => Promise.resolve(),
        handleCreateSubWorkItem: () => Promise.resolve(),
        pendingAttachments,
        setPendingAttachments,
        pendingBlockedByIssues,
        setPendingBlockedByIssues,
      }}
    >
      {children}
    </IssueModalContext.Provider>
  );
});
