/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import type { TIssueActivity } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProjectState } from "@/hooks/store/use-project-state";

type Props = { activityId: string; ends: "top" | "bottom" | undefined };

/** Name of a field in the history, as Jira names it. */
export const HISTORY_FIELD_LABELS: Record<string, string> = {
  state: "Status",
  priority: "Priority",
  assignees: "Assignee",
  labels: "Labels",
  name: "Summary",
  description: "Description",
  start_date: "Start date",
  target_date: "Due date",
  cycles: "Sprint",
  modules: "Module",
  parent: "Parent",
  estimate_point: "Estimate",
  estimate_points: "Estimate",
  estimate_categories: "Estimate",
  type: "Issue Type",
  milestone: "Milestone",
  queue: "Queue",
  link: "Link",
  attachment: "Attachment",
  blocked_by: "Blocked by",
  blocking: "Blocks",
  relates_to: "Relates to",
  duplicate: "Duplicate",
  start_before: "Starts before",
  start_after: "Starts after",
  finish_before: "Finishes before",
  finish_after: "Finishes after",
};

/** Fields whose history entries are shown in this (Jira) format. */
export const isHistoryEntry = (activity: TIssueActivity | undefined) =>
  !!activity &&
  (!!activity.external_source ||
    activity.field === "custom_field" ||
    (!!activity.field && activity.field in HISTORY_FIELD_LABELS) ||
    (!activity.field && activity.verb === "created"));

// fields where one entry adds or removes one value
const LIST_FIELDS = new Set([
  "assignees",
  "labels",
  "cycles",
  "modules",
  "link",
  "attachment",
  "blocked_by",
  "blocking",
  "relates_to",
  "duplicate",
  "start_before",
  "start_after",
  "finish_before",
  "finish_after",
]);
const CHIP_LABELS = new Set([
  "status",
  "issue type",
  "resolution",
  "priority",
  "sprint",
  "labels",
  "component",
  "fix versions",
  "epic link",
]);
const LONG_LABELS = new Set(["description", "environment", "summary"]);
const AVATAR_COLORS = ["#F97316", "#047857", "#2563EB", "#7C3AED", "#DB2777", "#0891B2", "#CA8A04", "#DC2626"];

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "?";

const colorFor = (name: string) =>
  AVATAR_COLORS[[...name].reduce((sum, char) => sum + char.charCodeAt(0), 0) % AVATAR_COLORS.length];

/** "January 16, 2024 at 4:27 PM", like Jira's History tab. */
const formatWhen = (value: string) => {
  const date = new Date(value);
  const day = date.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  const time = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${day} at ${time}`;
};

/** Text of an HTML value (descriptions saved by the editor). */
const plainText = (value: string) =>
  /<[a-z][\s\S]*>/i.test(value)
    ? (new DOMParser().parseFromString(value, "text/html").body.textContent?.trim() ?? "")
    : value;

function Chip({ text, color, struck }: { text: string; color?: string; struck?: boolean }) {
  return (
    <span
      className={cn("rounded-sm border px-1.5 py-0.5 text-caption-md-medium", {
        "border-accent-subtle bg-accent-subtle text-accent-primary": !color,
        "opacity-70": struck,
      })}
      style={color ? { borderColor: `${color}66`, backgroundColor: `${color}1f`, color } : undefined}
    >
      {text}
    </span>
  );
}

/**
 * One entry of the work item's history, shown the way Jira's History tab shows it: who (also people from Jira
 * without an account here), the exact date and time, which field, and old -> new.
 */
export const ExternalHistoryActivity = observer(function ExternalHistoryActivity(props: Props) {
  const { activityId, ends } = props;
  const {
    activity: { getActivityById },
  } = useIssueDetail();
  const { getProjectStates } = useProjectState();
  const [expanded, setExpanded] = useState(false);
  const activity = getActivityById(activityId);
  if (!activity) return null;

  const fromJira = activity.external_source === "jira";
  const name =
    (fromJira ? activity.external_actor_name : activity.actor_detail?.display_name) ||
    activity.actor_detail?.display_name ||
    activity.external_actor_name ||
    "HLIS Flow";
  const field = activity.field ?? "";
  const label = activity.external_field_name || HISTORY_FIELD_LABELS[field] || field.replace(/_/g, " ") || "Field";
  const isCreated = !activity.field && activity.verb === "created";
  const isWorklog = field === "worklog";
  const oldValue = activity.old_value ?? "";
  const newValue = activity.new_value ?? "";
  const isLong =
    LONG_LABELS.has(label.toLowerCase()) && (oldValue.length > 60 || newValue.length > 60 || label === "Description");
  const chip = CHIP_LABELS.has(label.toLowerCase());
  const states = label === "Status" ? (getProjectStates(activity.project) ?? []) : [];
  const stateColor = (text: string) => states.find((state) => state.name === text)?.color;

  let action: React.ReactNode;
  if (isCreated) action = "created the work item";
  else if (isWorklog) action = newValue ? `logged ${newValue}` : "deleted a work log";
  else if (LIST_FIELDS.has(field) && !fromJira) {
    action = (
      <>
        {newValue ? "added" : "removed"} the <span className="font-medium text-primary">{label}</span>
      </>
    );
  } else {
    action = (
      <>
        {oldValue && newValue ? "changed" : newValue ? "set" : "removed"} the{" "}
        <span className="font-medium text-primary">{label}</span>
      </>
    );
  }

  const showValues = !isCreated && !isWorklog && (oldValue || newValue);
  const listChange = LIST_FIELDS.has(field) && !fromJira;

  return (
    <div className={cn("relative flex gap-3", ends === "top" ? "pb-3" : ends === "bottom" ? "pt-3" : "py-3")}>
      <div className="absolute top-0 bottom-0 left-[15px] w-px bg-layer-3" aria-hidden />
      <div
        className="z-[4] flex size-8 flex-shrink-0 items-center justify-center rounded-full text-caption-md-medium text-white"
        style={{ backgroundColor: colorFor(name) }}
        aria-hidden
      >
        {initials(name)}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-body-xs-regular text-secondary">
          <span className="font-medium text-primary">{name}</span> {action}
          {fromJira && (
            <span className="ml-1.5 rounded-sm bg-layer-3 px-1 text-caption-sm-regular text-tertiary">Jira</span>
          )}
        </p>
        <p className="text-caption-sm-regular text-tertiary">{formatWhen(activity.created_at)}</p>
        {showValues &&
          (isLong ? (
            <div className="mt-1.5 text-caption-md-regular">
              <button
                type="button"
                className="text-accent-primary hover:underline"
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? "Hide change" : "Show change"}
              </button>
              {expanded && (
                <div className="mt-1.5 grid gap-2 md:grid-cols-2">
                  <div className="rounded-md border border-subtle bg-layer-1 p-2 whitespace-pre-wrap text-tertiary line-through">
                    {plainText(oldValue) || "None"}
                  </div>
                  <div className="rounded-md border border-subtle bg-layer-1 p-2 whitespace-pre-wrap text-primary">
                    {plainText(newValue) || "None"}
                  </div>
                </div>
              )}
            </div>
          ) : listChange ? (
            <p className="mt-1.5 text-body-xs-regular">
              {chip ? (
                <Chip text={newValue || oldValue} struck={!newValue} />
              ) : (
                <span className={newValue ? "text-primary" : "text-tertiary line-through"}>{newValue || oldValue}</span>
              )}
            </p>
          ) : (
            <p className="mt-1.5 flex flex-wrap items-center gap-2 text-body-xs-regular">
              {oldValue ? (
                chip ? (
                  <Chip text={oldValue} color={stateColor(oldValue)} struck />
                ) : (
                  <span className="text-primary">{oldValue}</span>
                )
              ) : (
                <span className="text-tertiary">None</span>
              )}
              <span className="text-tertiary">→</span>
              {newValue ? (
                chip ? (
                  <Chip text={newValue} color={stateColor(newValue)} />
                ) : (
                  <span className="text-primary">{newValue}</span>
                )
              ) : (
                <span className="text-tertiary">None</span>
              )}
            </p>
          ))}
      </div>
    </div>
  );
});
