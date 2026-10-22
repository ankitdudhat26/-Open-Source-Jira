/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
// plane imports
import { HistoryOutline } from "@makeplane/propel/icons";
// components
import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";

/** "History" in the sidebar: every change to work items, who made it and when. */
export const HistorySidebarItem = observer(function HistorySidebarItem() {
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  const { toggleSidebar, isExtendedSidebarOpened, toggleExtendedSidebar } = useAppTheme();
  const slug = workspaceSlug?.toString() ?? "";
  if (!slug) return null;

  return (
    <Link
      href={`/${slug}/history/`}
      onClick={() => {
        if (window.innerWidth < 768) toggleSidebar();
        if (isExtendedSidebarOpened) toggleExtendedSidebar(false);
      }}
    >
      <SidebarNavItem isActive={pathname.includes(`/${slug}/history`)}>
        <div className="flex items-center gap-1.5 py-[1px]">
          <HistoryOutline className="size-4 flex-shrink-0" />
          <p className="text-13 leading-5 font-medium">History</p>
        </div>
      </SidebarNavItem>
    </Link>
  );
});
