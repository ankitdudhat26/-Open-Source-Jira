/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { usePathname } from "next/navigation";
import { Outlet } from "react-router";
// plane imports
import { Header, Row } from "@plane/blocks/layout";
import { cn } from "@plane/utils";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { TabNavigationRoot } from "@/components/navigation/tab-navigation-root";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useFeatureAccess } from "@/hooks/use-feature-access";
import { useProjectNavigationPreferences } from "@/hooks/use-navigation-preferences";
// layouts
import { ProjectAuthWrapper } from "@/layouts/auth-layout/project-wrapper";
// local imports
import type { Route } from "./+types/layout";

/** The Roles & access feature of each project section, by its URL segment */
const SECTION_FEATURES: Record<string, string> = {
  issues: "work_items",
  cycles: "sprints",
  modules: "modules",
  views: "views",
  pages: "pages",
  intake: "intake",
  milestones: "milestones",
  resources: "resources",
};

function ProjectLayout({ params }: Route.ComponentProps) {
  // router
  const { workspaceSlug, projectId } = params;
  // store hooks
  const { sidebarCollapsed } = useAppTheme();
  // preferences
  const { preferences: projectPreferences } = useProjectNavigationPreferences();
  // Settings → Roles & access: a section whose viewing is denied to the person is not shown, even by its URL
  const pathname = usePathname();
  const { can } = useFeatureAccess(workspaceSlug);
  const section = pathname.split("/").filter(Boolean)[3];
  const sectionFeature = section ? SECTION_FEATURES[section] : undefined;
  const isSectionDenied = !!sectionFeature && !can(sectionFeature, "view", true, projectId);

  return (
    <>
      {projectPreferences.navigationMode === "TABBED" && (
        <div className="z-20">
          <Row className="flex h-header w-full items-center gap-2 border-b border-subtle bg-surface-1">
            <div className="flex h-full w-full items-center gap-2 divide-x divide-subtle">
              <div className="flex size-full flex-1 items-center gap-2">
                {sidebarCollapsed && (
                  <div className="shrink-0">
                    <AppSidebarToggleButton />
                  </div>
                )}
                <Header className={cn("h-full", { "pl-1.5": !sidebarCollapsed })}>
                  <Header.LeftItem className="flex h-full max-w-full items-center gap-2">
                    <TabNavigationRoot workspaceSlug={workspaceSlug} projectId={projectId} />
                  </Header.LeftItem>
                </Header>
              </div>
            </div>
          </Row>
        </div>
      )}
      <ProjectAuthWrapper workspaceSlug={workspaceSlug} projectId={projectId}>
        {isSectionDenied ? <NotAuthorizedView isProjectView className="h-auto" /> : <Outlet />}
      </ProjectAuthWrapper>
    </>
  );
}

export default observer(ProjectLayout);
