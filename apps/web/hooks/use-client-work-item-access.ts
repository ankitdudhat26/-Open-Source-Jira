/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssue } from "@plane/types";

type TWorkItemOwnership = Pick<TIssue, "created_by" | "project_id">;

/**
 * Whether the properties of the work items of a project — or of the given work item — can be edited. Clients (the
 * guests of a project) only view work items; they send requests through the project's Intake form.
 */
export type TCanEditProperties = (projectId: string | undefined, issue?: TWorkItemOwnership) => boolean;

/**
 * A client sees the properties of a work item as they are — at full colour, without the faded look of a disabled
 * control — but cannot open or change them.
 */
export const CLIENT_READ_ONLY_CLASS_NAME =
  "pointer-events-none select-text [&_*:disabled]:cursor-default [&_*:disabled]:text-secondary [&_*:disabled]:opacity-100";
