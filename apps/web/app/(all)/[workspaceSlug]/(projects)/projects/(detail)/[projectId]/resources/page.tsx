/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { PageHead } from "@/components/core/page-title";
import { ResourcesSection } from "@/components/milestones";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import type { Route } from "./+types/page";

/** Resources (roles and the members filling them) of a project that has no Milestones page, e.g. a dedicated one. */
function ProjectResourcesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  // store hooks
  const { getProjectById } = useProject();
  const { allowPermissions } = useUserPermissions();
  // derived values
  const project = getProjectById(projectId);
  const pageTitle = project?.name ? `${project.name} - Resources` : undefined;
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);

  return (
    <>
      <PageHead title={pageTitle} />
      <div className="h-full w-full">
        <ResourcesSection workspaceSlug={workspaceSlug} projectId={projectId} isAdmin={isAdmin} />
      </div>
    </>
  );
}

export default observer(ProjectResourcesPage);
