/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
// plane imports
import { ProjectsOutline } from "@makeplane/propel/icons";
// components
import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";

/** "All projects" in the sidebar: every project of the workspace in one table (like Jira's Spaces list). */
export const AllProjectsSidebarItem = observer(function AllProjectsSidebarItem() {
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  const { toggleSidebar, isExtendedSidebarOpened, toggleExtendedSidebar } = useAppTheme();
  const slug = workspaceSlug?.toString() ?? "";
  if (!slug) return null;

  return (
    <Link
      href={`/${slug}/all-projects/`}
      onClick={() => {
        if (window.innerWidth < 768) toggleSidebar();
        if (isExtendedSidebarOpened) toggleExtendedSidebar(false);
      }}
    >
      <SidebarNavItem isActive={pathname.includes(`/${slug}/all-projects`)}>
        <div className="flex items-center gap-1.5 py-[1px]">
          <ProjectsOutline className="size-4 flex-shrink-0" />
          <p className="text-13 leading-5 font-medium">All projects</p>
        </div>
      </SidebarNavItem>
    </Link>
  );
});
