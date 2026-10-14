/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@makeplane/propel/components/button";
import { ImportsOutline, MilestoneOutline } from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
// components
import { CommonProjectBreadcrumbs } from "@/components/breadcrumbs/common";
import { useProjectCrumbProps } from "@/components/breadcrumbs/use-project-crumb-props";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { MilestoneFormModal, SOWImportModal } from "@/components/milestones";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";

export const MilestonesListHeader = observer(function MilestonesListHeader() {
  // router
  const { workspaceSlug, projectId } = useParams();
  const projectCrumb = useProjectCrumbProps(workspaceSlug?.toString(), projectId?.toString());
  // states
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  // store hooks
  const { loader } = useProject();
  const { allowPermissions } = useUserPermissions();
  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);

  return (
    <Header>
      <Header.LeftItem>
        <div>
          <Breadcrumbs isLoading={loader === "init-loader"}>
            <CommonProjectBreadcrumbs
              workspaceSlug={workspaceSlug?.toString()}
              projectId={projectId?.toString()}
              {...projectCrumb}
            />
            <Breadcrumbs.Item
              component={
                <BreadcrumbLink
                  label="Milestones"
                  href={`/${workspaceSlug}/projects/${projectId}/milestones/`}
                  icon={<MilestoneOutline className="h-4 w-4 text-tertiary" />}
                  isLast
                />
              }
              isLast
            />
          </Breadcrumbs>
        </div>
      </Header.LeftItem>
      {isAdmin && workspaceSlug && projectId && (
        <Header.RightItem>
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            icon={<ImportsOutline />}
            label="Import SOW"
            onClick={() => setIsImportOpen(true)}
          />
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label="Add milestone"
            onClick={() => setIsCreateOpen(true)}
          />
          <SOWImportModal
            isOpen={isImportOpen}
            onClose={() => setIsImportOpen(false)}
            workspaceSlug={workspaceSlug.toString()}
            projectId={projectId.toString()}
          />
          <MilestoneFormModal
            isOpen={isCreateOpen}
            onClose={() => setIsCreateOpen(false)}
            workspaceSlug={workspaceSlug.toString()}
            projectId={projectId.toString()}
          />
        </Header.RightItem>
      )}
    </Header>
  );
});
