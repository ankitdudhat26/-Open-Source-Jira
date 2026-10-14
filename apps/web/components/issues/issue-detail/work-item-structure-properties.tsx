/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { LayerStackOutline, MilestoneOutline, ParentOutline } from "@makeplane/propel/icons";
import { Select } from "@plane/blocks/select";
import type { TMilestone, TWorkItemType } from "@plane/types";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
import { WorkItemTypeDot } from "@/components/issues/issue-modal/components/work-item-type-select";
import { IssueParentSelectRoot } from "@/components/issues/parent-select-root";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProject } from "@/hooks/store/use-project";
import { useProjectMilestones, useProjectWorkItemTypes } from "@/hooks/use-project-milestones";
// local imports
import type { TIssueOperations } from "./root";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  issueOperations: TIssueOperations;
  disabled: boolean;
};

/**
 * Type (Feature / Task / Bug), the feature a task or bug belongs to, and the milestone of the work item.
 * Replaces the generic "Parent" property of the work item sidebars.
 */
export const IssueWorkItemStructureProperties = observer(function IssueWorkItemStructureProperties(props: Props) {
  const { workspaceSlug, projectId, issueId, issueOperations, disabled } = props;
  // store hooks
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const { getProjectById } = useProject();
  const { workItemTypes, getTypeById, getTypeByKey } = useProjectWorkItemTypes(workspaceSlug, projectId);
  // derived values
  const issue = getIssueById(issueId);
  const isFixedCost = getProjectById(projectId)?.project_type === "fixed_cost";
  const { milestones } = useProjectMilestones(workspaceSlug, isFixedCost ? projectId : undefined);
  if (!issue) return null;

  const workItemType = getTypeById(issue.type_id);
  const isUnderFeature = workItemType?.key === "task" || workItemType?.key === "bug";
  const milestone = milestones?.find((item) => item.id === issue.milestone_id);

  return (
    <>
      {workItemTypes && (
        <SidebarPropertyListItem icon={LayerStackOutline} label="Type">
          <Select<TWorkItemType>
            getValues={() => workItemTypes}
            value={workItemType ?? null}
            onChange={(typeId) => {
              if (typeId === issue.type_id) return;
              const payload: { type_id: string; parent_id?: null } = { type_id: typeId };
              // a feature is not created under another work item
              if (getTypeById(typeId)?.key === "feature" && issue.parent_id) payload.parent_id = null;
              void issueOperations.update(workspaceSlug, projectId, issueId, payload);
            }}
            getOptionValue={(type) => type.id}
            getOptionLabel={(type) => type.name}
            getOptionIcon={(type) => <WorkItemTypeDot color={type.color} />}
            placeholder="Type"
            showSearch={false}
            pinSelected={false}
            disabled={disabled}
          >
            <Select.Trigger<TWorkItemType>
              variant="select-ghost-md"
              disabled={disabled}
              prependIcon={(types) => (types[0] ? <WorkItemTypeDot color={types[0].color} /> : undefined)}
            >
              {(types) => (
                <span className={types[0] ? "truncate" : "truncate text-placeholder"}>
                  {types[0] ? types[0].name : "No type"}
                </span>
              )}
            </Select.Trigger>
          </Select>
        </SidebarPropertyListItem>
      )}

      {workItemType?.key !== "feature" && (
        <SidebarPropertyListItem icon={ParentOutline} label={isUnderFeature ? "Feature" : "Parent"}>
          <IssueParentSelectRoot
            className="h-7.5 w-full grow"
            workspaceSlug={workspaceSlug}
            projectId={projectId}
            issueId={issueId}
            issueOperations={issueOperations}
            disabled={disabled}
            workItemTypeId={isUnderFeature ? getTypeByKey("feature")?.id : undefined}
          />
        </SidebarPropertyListItem>
      )}

      {isFixedCost && milestones && (
        <SidebarPropertyListItem icon={MilestoneOutline} label="Milestone">
          <Select<TMilestone>
            getValues={() => milestones}
            value={milestone ?? null}
            onChange={(milestoneId) =>
              void issueOperations.update(workspaceSlug, projectId, issueId, {
                milestone_id: milestoneId === issue.milestone_id ? null : milestoneId,
              })
            }
            getOptionValue={(item) => item.id}
            getOptionLabel={(item) => (item.code ? `${item.code} · ${item.name}` : item.name)}
            placeholder="Milestone"
            showSearch={milestones.length > 8}
            pinSelected={false}
            disabled={disabled}
          >
            <Select.Trigger<TMilestone> variant="select-ghost-md" disabled={disabled}>
              {(selected) => (
                <span className={selected[0] ? "truncate" : "truncate text-placeholder"}>
                  {selected[0] ? selected[0].name : "No milestone"}
                </span>
              )}
            </Select.Trigger>
          </Select>
        </SidebarPropertyListItem>
      )}
    </>
  );
});
