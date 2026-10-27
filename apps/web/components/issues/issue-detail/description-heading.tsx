/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";

/**
 * The work item description reads as body text under its own heading, a step below the title (the editor's
 * "large" font is brought down to 15px here; the "small" font setting is left as chosen).
 */
export const ISSUE_DESCRIPTION_EDITOR_CLASS =
  "[&.large-font]:[--font-size-regular:0.9375rem]! [&.large-font]:[--line-height-regular:1.5rem]!";

export function IssueDescriptionHeading() {
  const { t } = useTranslation();
  return <h3 className="text-body-md-semibold text-primary">{t("description")}</h3>;
}
