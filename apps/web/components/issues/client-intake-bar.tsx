/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { EUserPermissions } from "@plane/constants";
import { Button } from "@makeplane/propel/elements/button";
import { IntakeOutline } from "@makeplane/propel/icons";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
// services
import { intakeFormService } from "@/services/intake-form.service";

type Props = {
  workspaceSlug: string;
  projectId: string;
};

/**
 * Clients only view the project's work items; they send requests on the request form of the project's Intake. The
 * form opens logged in as they are here, so they go straight to it (and to the requests they already sent).
 */
export const ClientIntakeBar = observer(function ClientIntakeBar(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();
  const isClient = getProjectRoleByWorkspaceSlugAndProjectId(workspaceSlug, projectId) === EUserPermissions.GUEST;

  const { data: form } = useSWR(
    isClient ? ["CLIENT_INTAKE_FORM", workspaceSlug, projectId] : null,
    () => intakeFormService.fetch(workspaceSlug, projectId),
    { revalidateOnFocus: false }
  );

  if (!isClient || !form?.is_enabled || !form.url) return null;

  return (
    <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-3 border-t border-subtle bg-surface-1 px-page-x py-3">
      <div className="flex min-w-0 items-center gap-2">
        <IntakeOutline className="size-4 flex-shrink-0 text-tertiary" />
        <p className="text-body-xs-regular text-secondary">
          Need something from the team? Send a request and follow its status.
        </p>
      </div>
      <Button
        variant="primary"
        size="md"
        stretch="auto"
        type="button"
        onClick={() => window.open(form.url, "_blank", "noopener,noreferrer")}
      >
        <IntakeOutline className="size-3.5" />
        Add intake
      </Button>
    </div>
  );
});
