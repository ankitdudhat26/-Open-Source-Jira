/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// components
import { PageHead } from "@/components/core/page-title";
import { QueuesRoot } from "@/components/queues/queues-root";

function WorkspaceQueuesPage() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <PageHead title="Queues" />
      <QueuesRoot workspaceSlug={workspaceSlug?.toString() ?? ""} />
    </>
  );
}

export default observer(WorkspaceQueuesPage);
