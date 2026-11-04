/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions } from "@plane/constants";
// components
import { PageHead } from "@/components/core/page-title";
import { AllProjectsRoot } from "@/components/project/all-projects/root";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
import { useFeatureAccess } from "@/hooks/use-feature-access";

/** Every project of the workspace: workspace admins, and whoever Settings → Roles & access shows it to (others use
 * the Projects page). */
function AllProjectsPage() {
  const { workspaceSlug } = useParams();
  const { workspaceInfoBySlug } = useUserPermissions();
  const slug = workspaceSlug?.toString() ?? "";
  const role = workspaceInfoBySlug(slug)?.role;
  const { can } = useFeatureAccess(slug);
  const canSeeAllProjects = can("all_projects", "view", role === EUserPermissions.ADMIN);

  return (
    <>
      <PageHead title="All projects" />
      {canSeeAllProjects ? (
        <AllProjectsRoot workspaceSlug={slug} scope="all" />
      ) : (
        <div className="grid h-full w-full place-items-center px-page-x text-body-sm-regular text-tertiary">
          {role === undefined ? "Loading…" : "Your access does not include all projects. Ask a workspace admin."}
        </div>
      )}
    </>
  );
}

export default observer(AllProjectsPage);
