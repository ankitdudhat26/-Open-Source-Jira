/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { usePathname, useSearchParams } from "next/navigation";
// plane imports
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { ParentOutline } from "@makeplane/propel/icons";
import { cn } from "@plane/utils";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
import { usePlatformOS } from "@/hooks/use-platform-os";

export const HIERARCHY_VIEW_PARAM = "view";
export const HIERARCHY_VIEW_VALUE = "hierarchy";

/** Whether the work items page shows the Module / Milestone hierarchy instead of a layout. */
export const useIsHierarchyView = () => useSearchParams().get(HIERARCHY_VIEW_PARAM) === HIERARCHY_VIEW_VALUE;

/** Navigation between the hierarchy view and the regular layouts of the work items page. */
export const useHierarchyViewNavigation = () => {
  const router = useAppRouter();
  const pathname = usePathname();
  return {
    openHierarchy: () => router.push(`${pathname}?${HIERARCHY_VIEW_PARAM}=${HIERARCHY_VIEW_VALUE}`),
    closeHierarchy: () => router.push(pathname),
  };
};

/** "Hierarchy" button shown in front of the layout icons (List, Board, ...). */
export function HierarchyViewToggle(props: { isActive: boolean; onClick: () => void }) {
  const { isActive, onClick } = props;
  const { isMobile } = usePlatformOS();
  return (
    <Tooltip label="Hierarchy (module › feature › task)" disabled={isMobile}>
      <button
        type="button"
        aria-label="Hierarchy view"
        aria-pressed={isActive}
        className={cn(
          "group grid h-5.5 w-7 place-items-center overflow-hidden rounded-sm transition-all hover:bg-layer-transparent-hover",
          { "bg-layer-transparent-active hover:bg-layer-transparent-active": isActive }
        )}
        onClick={onClick}
      >
        <ParentOutline className={`size-3.5 ${isActive ? "text-primary" : "text-secondary"}`} />
      </button>
    </Tooltip>
  );
}
