/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
import { WorkspaceAccessRoot } from "@/components/settings/workspace/access/access-root";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { AccessWorkspaceSettingsHeader } from "./header";

function AccessSettingsPage() {
  const { workspaceSlug } = useParams();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  // only workspace admins manage who can do what
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  if (workspaceUserInfo && !isAdmin) return <NotAuthorizedView section="settings" className="h-auto" />;

  return (
    <SettingsContentWrapper header={<AccessWorkspaceSettingsHeader />}>
      <PageHead title="Roles & access" />
      <SettingsHeading
        title="Roles & access"
        description="Choose what each role can do in every feature, and give one person custom access. Admins always have full access."
      />
      <div className="mt-6">
        <WorkspaceAccessRoot workspaceSlug={workspaceSlug?.toString() ?? ""} />
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(AccessSettingsPage);
