/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import type { TIssueIdentifierProps } from "@plane/types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProject } from "@/hooks/store/use-project";
import { useProjectWorkItemTypes } from "@/hooks/use-project-milestones";
import { IdentifierText } from "@/components/issues/issue-detail/identifier-text";
import { WorkItemTypeIcon } from "@/components/issues/work-item-type-icon";

export const IssueIdentifier = observer(function IssueIdentifier(props: TIssueIdentifierProps) {
  const { projectId, variant, size, displayProperties, enableClickToCopyIdentifier = false } = props;
  // store hooks
  const { getProjectIdentifierById } = useProject();
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  // Determine if the component is using store data or not
  const isUsingStoreData = "issueId" in props;
  // derived values
  const issue = isUsingStoreData ? getIssueById(props.issueId) : null;
  const projectIdentifier = isUsingStoreData ? getProjectIdentifierById(projectId) : props.projectIdentifier;
  const issueSequenceId = isUsingStoreData ? issue?.sequence_id : props.issueSequenceId;
  const shouldRenderIssueID = displayProperties ? displayProperties.key : true;
  // Feature / Task / Bug icon in front of the key
  const { workspaceSlug } = useParams();
  const { getTypeById } = useProjectWorkItemTypes(workspaceSlug?.toString(), projectId);
  const workItemType = getTypeById(
    isUsingStoreData ? issue?.type_id : "issueTypeId" in props ? props.issueTypeId : undefined
  );
  const shouldRenderType = !!workItemType && (displayProperties ? displayProperties.issue_type !== false : true);

  if (!shouldRenderIssueID && !shouldRenderType) return null;

  return (
    <div className="flex shrink-0 items-center gap-1.5">
      {shouldRenderType && workItemType && <WorkItemTypeIcon type={workItemType} size="xs" />}
      {shouldRenderIssueID && (
        <IdentifierText
          identifier={`${projectIdentifier}-${issueSequenceId}`}
          enableClickToCopyIdentifier={enableClickToCopyIdentifier}
          variant={variant}
          size={size}
        />
      )}
    </div>
  );
});
