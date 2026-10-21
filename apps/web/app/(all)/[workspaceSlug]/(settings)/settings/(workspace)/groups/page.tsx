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
import { GroupsSettings } from "@/components/groups/groups-settings";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { GroupsWorkspaceSettingsHeader } from "./header";

function GroupsSettingsPage() {
  const { workspaceSlug } = useParams();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  if (workspaceUserInfo && !isAdmin) return <NotAuthorizedView section="settings" className="h-auto" />;

  return (
    <SettingsContentWrapper header={<GroupsWorkspaceSettingsHeader />}>
      <PageHead title="Groups & queues" />
      <SettingsHeading
        title="Groups & queues"
        description="Put people in groups such as DevOps and choose what the group may do. A group with a queue receives work items from every project; its members see them read only, take one by assigning it to themselves and can then work on it."
      />
      <div className="mt-6">
        <GroupsSettings workspaceSlug={workspaceSlug?.toString() ?? ""} isEditable={isAdmin} />
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(GroupsSettingsPage);
