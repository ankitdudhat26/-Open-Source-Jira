/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// components
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { EmptyStateDetailed } from "@plane/blocks/empty-state";
import { EIssuesStoreType } from "@plane/types";
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useUserPermissions } from "@/hooks/store/user";
import { useFeatureAccess } from "@/hooks/use-feature-access";

export const ProjectViewEmptyState = observer(function ProjectViewEmptyState() {
  // router
  const { projectId } = useParams();
  // store hooks
  const { toggleCreateIssueModal } = useCommandPalette();
  const { allowPermissions } = useUserPermissions();

  // auth
  // clients (project guests) only view work items
  const isCreatingIssueAllowed = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT
  );
  const { can } = useFeatureAccess();
  const canCreateWorkItems = can("work_items", "create", isCreatingIssueAllowed, projectId?.toString());

  return (
    // TODO: Add translation
    <EmptyStateDetailed
      assetKey="work-item"
      title="View work items will appear here"
      description="Work items help you track individual pieces of work. With work items, keep track of what's going on, who is working on it, and what's done."
      // hidden without Settings → Roles & access: Work items → Create
      actions={
        canCreateWorkItems
          ? [
              {
                label: "New work item",
                onClick: () => {
                  toggleCreateIssueModal(true, EIssuesStoreType.PROJECT_VIEW);
                },
                disabled: !isCreatingIssueAllowed,
                variant: "primary",
              },
            ]
          : []
      }
    />
  );
});
