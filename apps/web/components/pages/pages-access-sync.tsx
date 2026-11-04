/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// hooks
import { EPageStoreType, usePageStore } from "@/hooks/store";
import { useFeatureAccess } from "@/hooks/use-feature-access";

/**
 * Hands Settings → Roles & access for pages to the page store, whose permission getters (edit, lock, archive,
 * delete, duplicate…) hide what the user's role may not do. Renders nothing.
 */
export const PagesAccessSync = observer(function PagesAccessSync() {
  const { workspaceSlug, projectId } = useParams();
  const { can } = useFeatureAccess(workspaceSlug?.toString());
  const { setFeatureAccess } = usePageStore(EPageStoreType.PROJECT);
  const project = projectId?.toString();
  const create = can("pages", "create", true, project);
  const edit = can("pages", "edit", true, project);
  const remove = can("pages", "delete", true, project);

  useEffect(() => {
    setFeatureAccess({ create, edit, delete: remove });
  }, [create, edit, remove, setFeatureAccess]);

  return null;
});
