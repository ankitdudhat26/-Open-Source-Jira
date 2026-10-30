/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useParams } from "next/navigation";
// components
import { IntakePortal } from "@/components/intake-form/intake-portal";

export function meta() {
  return [{ title: "Requests" }, { name: "robots", content: "noindex" }];
}

/** The page behind a project's Intake link: invited clients log in, send requests and follow them. */
export default function IntakeFormPage() {
  const { anchor } = useParams<{ anchor: string }>();
  return <IntakePortal anchor={anchor} />;
}
