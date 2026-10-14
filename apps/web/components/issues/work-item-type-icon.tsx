/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { LayerStackOutline, TickOutline, WarningCircleOutline } from "@makeplane/propel/icons";
import type { TWorkItemType } from "@plane/types";

const TYPE_GLYPHS = {
  feature: LayerStackOutline,
  task: TickOutline,
  bug: WarningCircleOutline,
};

/** Coloured square with a glyph per work item type, like Jira's issue type icons. */
export function WorkItemTypeIcon(props: { type: TWorkItemType; size?: "xs" | "sm" }) {
  const { type, size = "sm" } = props;
  const Glyph = TYPE_GLYPHS[type.key] ?? TickOutline;
  const box = size === "xs" ? "size-3.5" : "size-4";
  const glyph = size === "xs" ? "size-2.5" : "size-3";
  return (
    <span
      role="img"
      aria-label={type.name}
      title={type.name}
      className={`grid ${box} flex-shrink-0 place-items-center rounded-[3px] text-white`}
      style={{ backgroundColor: type.color }}
    >
      <Glyph className={glyph} />
    </span>
  );
}
