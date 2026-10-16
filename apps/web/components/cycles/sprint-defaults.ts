/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ICycle } from "@plane/types";
import { getDate, renderFormattedPayloadDate } from "@plane/utils";

/** Jira's default sprint length. */
export const DEFAULT_SPRINT_DAYS = 14;

/**
 * Jira style defaults for a new sprint: "<PROJECT> Sprint <n>", running two weeks from the day after the latest
 * sprint ends (or from today when there is none or it is already over). Starting after the last sprint keeps the
 * dates clear of the existing sprints.
 */
export const getNewSprintDefaults = (
  existingSprints: Pick<ICycle, "name" | "end_date">[],
  projectIdentifier: string | undefined,
  today: Date = new Date()
): Pick<ICycle, "name" | "start_date" | "end_date"> => {
  const numbers = existingSprints
    .map((sprint) => /sprint\s+(\d+)\s*$/i.exec(sprint.name ?? "")?.[1])
    .filter((value): value is string => !!value)
    .map(Number);
  const nextNumber = Math.max(existingSprints.length, ...numbers) + 1;

  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const latestEnd = existingSprints
    .map((sprint) => getDate(sprint.end_date))
    .filter((date): date is Date => !!date)
    .reduce<Date | undefined>((latest, date) => (!latest || date > latest ? date : latest), undefined);
  const start = latestEnd && latestEnd >= startOfToday ? new Date(latestEnd) : new Date(startOfToday);
  if (latestEnd && latestEnd >= startOfToday) start.setDate(start.getDate() + 1);
  const end = new Date(start);
  end.setDate(start.getDate() + DEFAULT_SPRINT_DAYS - 1);

  return {
    name: `${projectIdentifier ? `${projectIdentifier} ` : ""}Sprint ${nextNumber}`,
    start_date: renderFormattedPayloadDate(start) ?? null,
    end_date: renderFormattedPayloadDate(end) ?? null,
  };
};
