/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { ProjectsOutline } from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";

export const AllProjectsHeader = observer(function AllProjectsHeader() {
  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink label="All projects" icon={<ProjectsOutline className="size-5 text-secondary" />} />
            }
          />
        </Breadcrumbs>
      </Header.LeftItem>
    </Header>
  );
});
