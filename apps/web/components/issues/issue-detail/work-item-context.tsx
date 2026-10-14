/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { MilestoneOutline, ModuleOutline, UserOutline } from "@makeplane/propel/icons";
import { getFileURL } from "@plane/utils";
// components
import { WorkItemTypeIcon } from "@/components/issues/work-item-type-icon";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useModule } from "@/hooks/store/use-module";
import { useProject } from "@/hooks/store/use-project";
import { useProjectMilestones, useProjectResources, useProjectWorkItemTypes } from "@/hooks/use-project-milestones";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
};

function ContextItem(props: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-caption-sm-medium text-tertiary">{props.label}</span>
      <div className="flex min-w-0 items-center gap-1.5 text-body-xs-medium text-primary">{props.children}</div>
    </div>
  );
}

const linkClassName = "truncate hover:underline";

/**
 * Where the work item sits in the project structure: its type, SOW ID, milestone, module, feature and the
 * resource (role) that delivers it with the member mapped to that role.
 */
export const WorkItemContext = observer(function WorkItemContext(props: Props) {
  const { workspaceSlug, projectId, issueId } = props;
  // store hooks
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const { getProjectById, getProjectIdentifierById } = useProject();
  const { getModuleById } = useModule();
  const { getUserDetails } = useMember();
  const { getTypeById } = useProjectWorkItemTypes(workspaceSlug, projectId);
  // derived values
  const issue = getIssueById(issueId);
  const isFixedCost = getProjectById(projectId)?.project_type === "fixed_cost";
  const { milestones } = useProjectMilestones(workspaceSlug, isFixedCost ? projectId : undefined);
  const { resources } = useProjectResources(workspaceSlug, isFixedCost ? projectId : undefined);
  if (!issue) return null;

  const workItemType = getTypeById(issue.type_id);
  const milestone = milestones?.find((item) => item.id === issue.milestone_id);
  const modules = (issue.module_ids ?? []).map((moduleId) => getModuleById(moduleId)).filter((module) => !!module);
  const feature = issue.parent_id ? getIssueById(issue.parent_id) : undefined;
  const featureType = feature ? getTypeById(feature.type_id) : undefined;
  const resource = resources?.find((item) => item.label_id && issue.label_ids?.includes(item.label_id));
  const resourceMember = resource?.member_id ? getUserDetails(resource.member_id) : undefined;
  const projectIdentifier = getProjectIdentifierById(projectId);

  // nothing to show for a plain work item outside the SOW structure
  if (!workItemType && !milestone && modules.length === 0 && !resource && !issue.external_id) return null;

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-md border border-subtle bg-layer-1 px-3 py-2.5 sm:grid-cols-3">
      {workItemType && (
        <ContextItem label="Type">
          <WorkItemTypeIcon type={workItemType} size="xs" />
          <span className="truncate">{workItemType.name}</span>
          {issue.external_source === "sow" && issue.external_id && (
            <span className="shrink-0 rounded-sm bg-layer-2 px-1 text-caption-sm-medium text-secondary">
              {issue.external_id}
            </span>
          )}
        </ContextItem>
      )}
      {milestone && (
        <ContextItem label="Milestone">
          <MilestoneOutline className="size-3.5 shrink-0 text-tertiary" />
          <Link href={`/${workspaceSlug}/projects/${projectId}/milestones`} className={linkClassName}>
            {milestone.code ? `${milestone.code} · ${milestone.name}` : milestone.name}
          </Link>
        </ContextItem>
      )}
      {modules.length > 0 && (
        <ContextItem label={modules.length > 1 ? "Modules" : "Module"}>
          <ModuleOutline className="size-3.5 shrink-0 text-tertiary" />
          <span className="flex min-w-0 flex-wrap gap-x-1.5">
            {modules.map((module) => (
              <Link
                key={module.id}
                href={`/${workspaceSlug}/projects/${projectId}/modules/${module.id}`}
                className={linkClassName}
              >
                {module.name}
              </Link>
            ))}
          </span>
        </ContextItem>
      )}
      {feature && (
        <ContextItem label={featureType?.key === "feature" ? "Feature" : "Parent"}>
          {featureType && <WorkItemTypeIcon type={featureType} size="xs" />}
          <Link
            href={`/${workspaceSlug}/browse/${projectIdentifier}-${feature.sequence_id}/`}
            className={linkClassName}
            title={feature.name}
          >
            {feature.name}
          </Link>
        </ContextItem>
      )}
      {resource && (
        <ContextItem label="Resource">
          <span className="truncate" title={resource.responsibilities}>
            {resource.code ? `${resource.code} · ${resource.role}` : resource.role}
          </span>
        </ContextItem>
      )}
      {resource && (
        <ContextItem label="Mapped member">
          {resourceMember ? (
            <>
              <Avatar
                alt={resourceMember.display_name}
                fallback={resourceMember.display_name?.[0]?.toUpperCase()}
                src={getFileURL(resourceMember.avatar_url)}
                size="2xs"
              />
              <span className="truncate">{resourceMember.display_name}</span>
            </>
          ) : (
            <>
              <UserOutline className="size-3.5 shrink-0 text-tertiary" />
              <Link
                href={`/${workspaceSlug}/projects/${projectId}/milestones`}
                className="text-placeholder hover:underline"
              >
                Not mapped
              </Link>
            </>
          )}
        </ContextItem>
      )}
    </div>
  );
});
