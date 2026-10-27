/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { HlinkLogo } from "@plane/blocks/icons";

/** Loading indicator: the HLIS Flow logo, gently pulsing. */
export function LogoSpinner() {
  return (
    <div className="flex items-center justify-center" role="status" aria-label="Loading">
      <HlinkLogo className="h-6 w-auto animate-pulse object-contain sm:h-11" />
    </div>
  );
}
