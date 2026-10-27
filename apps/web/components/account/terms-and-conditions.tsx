/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { EAuthModes } from "@plane/constants";

interface TermsAndConditionsProps {
  authType?: EAuthModes;
}

/** No third party legal links: HLIS Flow has no separate terms page, so nothing is shown. */
export function TermsAndConditions(_props: TermsAndConditionsProps) {
  return null;
}
