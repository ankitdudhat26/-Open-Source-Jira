/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { DeleteOutline } from "@makeplane/propel/icons";
// plane imports
import { Tooltip } from "@makeplane/propel/components/tooltip";

type Props = {
  onDelete: () => void;
};

/** Takes the image out of the content (a comment, a description) while it is being edited. */
export function ImageDeleteAction(props: Props) {
  const { onDelete } = props;

  return (
    <Tooltip label="Remove image">
      <button
        type="button"
        // keep the editor's selection on the image until the click removes it
        onMouseDown={(event) => event.preventDefault()}
        onClick={(event) => {
          event.stopPropagation();
          onDelete();
        }}
        className="grid h-full flex-shrink-0 place-items-center text-white/60 transition-colors hover:text-white"
        aria-label="Remove image"
      >
        <DeleteOutline className="size-3" />
      </button>
    </Tooltip>
  );
}
