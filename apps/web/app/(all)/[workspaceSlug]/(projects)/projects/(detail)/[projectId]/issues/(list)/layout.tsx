/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { Outlet } from "react-router";
import { useParams } from "next/navigation";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { ClientIntakeBar } from "@/components/issues/client-intake-bar";
import { ProjectIssuesHeader } from "./header";
import { ProjectIssuesMobileHeader } from "./mobile-header";

export default function ProjectIssuesLayout() {
  const { workspaceSlug, projectId } = useParams();
  return (
    <>
      <AppHeader header={<ProjectIssuesHeader />} mobileHeader={<ProjectIssuesMobileHeader />} />
      <ContentWrapper>
        <Outlet />
      </ContentWrapper>
      {workspaceSlug && projectId && <ClientIntakeBar workspaceSlug={workspaceSlug} projectId={projectId} />}
    </>
  );
}
