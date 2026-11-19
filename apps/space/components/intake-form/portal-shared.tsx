/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Select } from "@plane/blocks/select";
import type { TIssuePriorities, TStateGroups } from "@plane/types";

/** Shared by the request form, Request Status, Work Items, a work item's details and the notifications. */

export type TStateLite = { id: string; name: string; color: string; group: TStateGroups };
export type TLabelLite = { id: string; name: string; color: string };

export type TWorkItemRow = {
  id: string;
  project_id: string;
  project_name: string;
  key: string;
  name: string;
  type: { name: string; color: string } | null;
  state: TStateLite | null;
  priority: TIssuePriorities;
  assignees: { id: string; name: string }[];
  labels: TLabelLite[];
  start_date: string | null;
  target_date: string | null;
  modules: { id: string; name: string }[];
  sprint: { id: string; name: string } | null;
  parent: { id: string; key: string; name: string } | null;
  milestone: { id: string; name: string } | null;
  /** who created it; the client's own work items (their requests) are marked */
  created_by: { id: string; name: string } | null;
  is_mine: boolean;
  created_at: string;
  updated_at: string;
};

export type TWorkItemDetail = TWorkItemRow & {
  description_html: string;
  allowed_states: TStateLite[];
  attachments: { id: string; name: string; size: number; created_at: string; url: string }[];
  comments: { id: string; author: string; is_mine: boolean; comment_html: string; created_at: string }[];
  history: {
    id: string;
    actor: string;
    field: string | null;
    verb: string;
    old_value: string | null;
    new_value: string | null;
    text: string;
    created_at: string;
  }[];
  /** every state of the project, to draw a change of state with its colours */
  states: TStateLite[];
};

export type TNotification = {
  id: string;
  kind: string;
  issue_id: string | null;
  key: string;
  title: string;
  text: string;
  created_at: string;
};

export const PRIORITY_LABELS: Record<string, string> = {
  urgent: "Urgent",
  high: "High",
  medium: "Medium",
  low: "Low",
  none: "None",
};

export const MAX_FILE_SIZE = 5 * 1024 * 1024;

export const getJson = async <T,>(url: string): Promise<T> => {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as T;
};

/** Sends JSON (or a file as form data) and returns the parsed body, or throws with the API's error message. */
export const send = async <T,>(url: string, method: string, body: Record<string, unknown> | FormData): Promise<T> => {
  const response = await fetch(url, {
    method,
    credentials: "include",
    ...(body instanceof FormData
      ? { body }
      : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = (await response.json().catch(() => ({}))) as T & { error?: string };
  if (!response.ok) throw new Error(data.error ?? "Something went wrong. Try again.");
  return data;
};

/** Whether the editor's HTML has no text (an empty paragraph, line breaks…). */
export const isEmptyHtml = (html: string) =>
  !html ||
  (!/<(img|table|hr|pre|ul|ol)\b/i.test(html) &&
    !html
      .replace(/<[^>]*>/g, "")
      .replace(/&nbsp;/g, " ")
      .trim());

export function ColorDot({ color }: { color?: string }) {
  return (
    <span className="inline-block size-2.5 shrink-0 rounded-full" style={{ backgroundColor: color || "#6B7280" }} />
  );
}

/** A label as the app shows it: its name in a chip with a dot of its colour. */
export function LabelChip({ label }: { label: TLabelLite }) {
  return (
    <span className="inline-flex max-w-40 items-center gap-1 rounded-sm border border-strong px-1.5 py-0.5 text-caption-sm-regular text-secondary">
      <ColorDot color={label.color} />
      <span className="truncate">{label.name}</span>
    </span>
  );
}

/** The initials of a name, for a small avatar. */
export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "?";

export type TOption = { id: string; name: string; color?: string };

export type TOptionSelectProps = {
  options: TOption[];
  placeholder: string;
  icon?: (option: TOption) => React.ReactNode;
  /** md for a filter in a toolbar, lg (default) for a form field */
  size?: "md" | "lg";
} & (
  | { multiple?: false; value: string; onChange: (id: string) => void }
  | {
      multiple: true;
      value: string[];
      onChange: (ids: string[]) => void;
    }
);

/** A field-style dropdown whose options (and selected value) carry an icon: type colour, priority, label colour. */
export function OptionSelect(props: TOptionSelectProps) {
  const { options, placeholder, icon, size = "lg" } = props;
  const byId = new Map(options.map((option) => [option.id, option]));
  const common = {
    getValues: () => options,
    getOptionValue: (option: TOption) => option.id,
    getOptionLabel: (option: TOption) => option.name,
    getOptionIcon: icon,
    placeholder,
    showSearch: options.length > 8,
    pinSelected: false,
  };
  const trigger = (
    // the select chrome's border width is dropped from its class list in this app — set it here
    <Select.Trigger<TOption> variant={`select-${size}`} className="border">
      {(selected) => (
        <span className="flex min-w-0 grow items-center gap-1.5 text-left">
          {selected.length === 0 ? (
            <span className="truncate text-placeholder">{placeholder}</span>
          ) : selected.length === 1 ? (
            <>
              {icon?.(selected[0])}
              <span className="truncate">{selected[0].name}</span>
            </>
          ) : (
            <>
              <span className="flex shrink-0 items-center -space-x-0.5">
                {selected.slice(0, 4).map((option) => (
                  <span key={option.id} className="ring-layer-2 flex rounded-full ring-2">
                    {icon?.(option)}
                  </span>
                ))}
              </span>
              <span className="truncate">{selected.map((option) => option.name).join(", ")}</span>
            </>
          )}
        </span>
      )}
    </Select.Trigger>
  );
  if (props.multiple)
    return (
      <Select<TOption>
        {...common}
        multiple
        value={props.value.flatMap((id) => byId.get(id) ?? [])}
        onChange={props.onChange}
      >
        {trigger}
      </Select>
    );
  return (
    <Select<TOption> {...common} value={byId.get(props.value) ?? null} onChange={props.onChange}>
      {trigger}
    </Select>
  );
}
