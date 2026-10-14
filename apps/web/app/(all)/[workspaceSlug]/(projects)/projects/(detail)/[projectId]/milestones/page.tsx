/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@plane/utils";
// components
import { PageHead } from "@/components/core/page-title";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { DeliverablesTable, MilestonesRoot, ResourcesSection } from "@/components/milestones";
import { WorkItemHierarchyTable } from "@/components/work-item-hierarchy/hierarchy-table";
import { useAppRouter } from "@/hooks/use-app-router";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import type { Route } from "./+types/page";

const TABS = [
  { key: "milestones", label: "Milestones" },
  { key: "work-items", label: "Work items" },
  { key: "resources", label: "Resources" },
  { key: "deliverables", label: "Deliverables" },
];

function ProjectMilestonesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  // Milestones | Work items (milestone -> module -> feature -> task) | Resources | Deliverables
  const router = useAppRouter();
  const pathname = usePathname();
  const tabParam = useSearchParams().get("tab");
  const activeTab = TABS.some((tab) => tab.key === tabParam) ? tabParam : "milestones";
  const openTab = (key: string) => router.push(key === "milestones" ? pathname : `${pathname}?tab=${key}`);
  const { allowPermissions } = useUserPermissions();
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  // store hooks
  const { getProjectById } = useProject();
  // derived values
  const project = getProjectById(projectId);
  const pageTitle = project?.name ? `${project.name} - Milestones` : undefined;

  if (project && project.project_type !== "fixed_cost")
    return (
      <div className="flex h-full w-full items-center justify-center p-page-x text-center text-body-xs-regular text-tertiary">
        Milestones are available for Fixed Cost projects. Change the project type in project settings to use them.
      </div>
    );

  return (
    <>
      <PageHead title={pageTitle} />
      <div className="flex h-full w-full flex-col">
        <div className="flex shrink-0 items-center gap-4 border-b border-subtle px-page-x" role="tablist">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              onClick={() => openTab(tab.key)}
              className={cn(
                "-mb-px border-b-2 py-2.5 text-body-xs-medium",
                activeTab === tab.key
                  ? "border-accent-strong text-primary"
                  : "border-transparent text-tertiary hover:text-secondary"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1">
          {activeTab === "work-items" && (
            <>
              <WorkItemHierarchyTable workspaceSlug={workspaceSlug} projectId={projectId} groupBy="milestone" />
              <IssuePeekOverview />
            </>
          )}
          {activeTab === "milestones" && (
            <MilestonesRoot
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              onOpenWorkItems={() => openTab("work-items")}
            />
          )}
          {activeTab === "resources" && (
            <ResourcesSection workspaceSlug={workspaceSlug} projectId={projectId} isAdmin={isAdmin} />
          )}
          {activeTab === "deliverables" && <DeliverablesTable workspaceSlug={workspaceSlug} projectId={projectId} />}
        </div>
      </div>
    </>
  );
}

export default observer(ProjectMilestonesPage);
