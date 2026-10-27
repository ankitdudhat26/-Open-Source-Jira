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

function AllProjectsPage() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <PageHead title="All projects" />
      <AllProjectsRoot workspaceSlug={workspaceSlug?.toString() ?? ""} />
    </>
  );
}

export default observer(AllProjectsPage);
