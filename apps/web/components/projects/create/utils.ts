/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { RANDOM_EMOJI_CODES } from "@plane/constants";
import type { IProject } from "@plane/types";
import { getRandomCoverImage } from "@/helpers/cover-image.helper";

export const getProjectFormValues = (): Partial<IProject> => ({
  cover_image_url: getRandomCoverImage(),
  description: "",
  logo_props: {
    in_use: "emoji",
    emoji: {
      value: RANDOM_EMOJI_CODES[Math.floor(Math.random() * RANDOM_EMOJI_CODES.length)],
    },
  },
  identifier: "",
  name: "",
  network: 2,
  project_lead: null,
  empro_id: "",
  project_type: "fixed_cost",
  deliverables: [""],
  milestones: [{ name: "", amount: null }],
});

/** Drops empty deliverable / milestone rows; only fixed cost projects are billed by milestones. */
export const getProjectCreatePayload = (formData: Partial<IProject>): Partial<IProject> => {
  const isFixedCost = formData.project_type === "fixed_cost";
  return {
    ...formData,
    empro_id: formData.empro_id?.trim() || null,
    deliverables: isFixedCost ? (formData.deliverables ?? []).map((name) => name.trim()).filter(Boolean) : [],
    milestones: isFixedCost
      ? (formData.milestones ?? [])
          .map((milestone) => ({ name: milestone.name.trim(), amount: milestone.amount || null }))
          .filter((milestone) => milestone.name)
      : [],
  };
};
