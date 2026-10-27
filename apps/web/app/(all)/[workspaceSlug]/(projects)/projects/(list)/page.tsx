/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// components
import { PageHead } from "@/components/core/page-title";
import { AllProjectsRoot } from "@/components/project/all-projects/root";

/** The projects the signed-in user is a member of, in the same table as All projects. */
function ProjectsPage() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <PageHead title="Projects" />
      <AllProjectsRoot workspaceSlug={workspaceSlug?.toString() ?? ""} scope="mine" />
    </>
  );
}

export default observer(ProjectsPage);
