/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
// plane imports
import { InboxOutline } from "@makeplane/propel/icons";
// components
import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useWorkspaceQueues } from "@/hooks/use-groups-queues";

/** "Queues" in the sidebar, for people in a group with a queue (e.g. DevOps); the badge counts waiting work items. */
export const QueueSidebarItem = observer(function QueueSidebarItem() {
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  const { toggleSidebar, isExtendedSidebarOpened, toggleExtendedSidebar } = useAppTheme();
  const slug = workspaceSlug?.toString() ?? "";
  const { queues } = useWorkspaceQueues(slug || undefined);

  if (!slug || !queues?.length) return null;
  // waiting = not taken by anyone yet, in the queues the user is a member of
  const waiting = queues.filter((queue) => queue.is_member).reduce((sum, queue) => sum + queue.counts.unassigned, 0);
  const href = `/${slug}/queues/`;

  return (
    <Link
      href={href}
      onClick={() => {
        if (window.innerWidth < 768) toggleSidebar();
        if (isExtendedSidebarOpened) toggleExtendedSidebar(false);
      }}
    >
      <SidebarNavItem isActive={pathname.includes(`/${slug}/queues`)}>
        <div className="flex items-center gap-1.5 py-[1px]">
          <InboxOutline className="size-4 flex-shrink-0" />
          <p className="text-13 leading-5 font-medium">Queues</p>
        </div>
        {waiting > 0 && (
          <span
            className="ml-auto rounded-full bg-accent-primary px-1.5 text-caption-sm-medium text-on-color"
            aria-label={`${waiting} waiting`}
          >
            {waiting}
          </span>
        )}
      </SidebarNavItem>
    </Link>
  );
});
