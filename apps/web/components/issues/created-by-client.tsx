/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Avatar } from "@makeplane/propel/components/avatar";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import type { TIssue } from "@plane/types";

type Props = { creator: NonNullable<TIssue["created_by_detail"]> };

/** The person who created a work item when the member list does not have them — a client of the Intake link. */
export function CreatedByClient({ creator }: Props) {
  const name = `${creator.first_name ?? ""} ${creator.last_name ?? ""}`.trim() || creator.display_name || creator.email;
  return (
    <Tooltip label={`${name} · ${creator.email} (client)`}>
      <span className="flex min-w-0 items-center gap-2">
        <Avatar alt={name} fallback={name[0]?.toUpperCase() ?? "?"} size="sm" />
        <span className="truncate text-body-xs-medium leading-5 text-secondary">{name}</span>
        <span className="shrink-0 rounded-sm bg-layer-3 px-1 text-caption-sm-medium text-tertiary">Client</span>
      </span>
    </Tooltip>
  );
}
