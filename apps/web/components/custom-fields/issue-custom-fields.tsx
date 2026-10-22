/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { PropertiesOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import { cn, renderFormattedDate } from "@plane/utils";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useIssueCustomFieldValues, useProjectCustomFields } from "@/hooks/use-custom-fields";
// services
import type { TCustomField, TCustomFieldValue } from "@/services/custom-field.service";
import { customFieldService } from "@/services/custom-field.service";

type Props = { workspaceSlug: string; projectId: string; issueId: string; disabled: boolean };

const INPUT =
  "w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-body-xs-regular text-primary hover:border-subtle focus:border-accent-strong focus:outline-none disabled:hover:border-transparent";

const errorMessage = (error: unknown) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string"
    ? error.error
    : "The value could not be saved.";

/** A text-like field saved when the input loses focus (or Enter is pressed). */
function DraftInput(props: {
  value: TCustomFieldValue;
  type: "text" | "number" | "url";
  disabled: boolean;
  onSave: (value: string) => void;
  label: string;
}) {
  const { value, type, disabled, onSave, label } = props;
  const saved = value === null || value === undefined ? "" : String(value);
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);
  if (disabled && type === "url" && saved)
    return (
      <a
        href={saved}
        target="_blank"
        rel="noopener noreferrer"
        className="truncate px-2 text-accent-primary hover:underline"
      >
        {saved}
      </a>
    );
  return (
    <input
      className={INPUT}
      type={type === "number" ? "number" : "text"}
      value={draft}
      disabled={disabled}
      aria-label={label}
      placeholder={disabled ? "None" : `Add ${label.toLowerCase()}`}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => draft !== saved && onSave(draft)}
      onKeyDown={(event) => event.key === "Enter" && (event.target as HTMLInputElement).blur()}
    />
  );
}

function DraftTextarea(props: {
  value: TCustomFieldValue;
  disabled: boolean;
  onSave: (value: string) => void;
  label: string;
}) {
  const { value, disabled, onSave, label } = props;
  const saved = value === null || value === undefined ? "" : String(value);
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);
  return (
    <textarea
      className={cn(INPUT, "min-h-8 resize-y")}
      rows={Math.min(Math.max(draft.split("\n").length, 1), 6)}
      value={draft}
      disabled={disabled}
      aria-label={label}
      placeholder={disabled ? "None" : `Add ${label.toLowerCase()}`}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => draft !== saved && onSave(draft)}
    />
  );
}

function FieldEditor(props: {
  field: TCustomField;
  value: TCustomFieldValue;
  disabled: boolean;
  projectId: string;
  onSave: (value: TCustomFieldValue) => void;
}) {
  const { field, value, disabled, projectId, onSave } = props;
  const { getUserDetails } = useMember();
  switch (field.field_type) {
    case "text":
    case "url":
      return (
        <DraftInput value={value} type={field.field_type} disabled={disabled} onSave={onSave} label={field.name} />
      );
    case "number":
      return (
        <DraftInput
          value={value}
          type="number"
          disabled={disabled}
          onSave={(text) => onSave(text === "" ? null : Number(text))}
          label={field.name}
        />
      );
    case "textarea":
      return <DraftTextarea value={value} disabled={disabled} onSave={onSave} label={field.name} />;
    case "date":
      return disabled ? (
        <span className="px-2 text-body-xs-regular text-primary">
          {value ? renderFormattedDate(String(value)) : "None"}
        </span>
      ) : (
        <input
          className={INPUT}
          type="date"
          value={value ? String(value) : ""}
          aria-label={field.name}
          onChange={(event) => onSave(event.target.value || null)}
        />
      );
    case "checkbox":
      return (
        <label className="flex items-center gap-2 px-2 text-body-xs-regular text-primary">
          <input
            type="checkbox"
            checked={value === true}
            disabled={disabled}
            onChange={(event) => onSave(event.target.checked)}
          />
          {value === true ? "Yes" : "No"}
        </label>
      );
    case "select":
      return (
        <select
          className={INPUT}
          value={value ? String(value) : ""}
          disabled={disabled}
          aria-label={field.name}
          onChange={(event) => onSave(event.target.value || null)}
        >
          <option value="">None</option>
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    case "multi_select": {
      const selected = Array.isArray(value) ? value.map(String) : [];
      return (
        <div className="flex flex-wrap gap-1 px-2 py-1">
          {(disabled ? selected : field.options).map((option) => {
            const active = selected.includes(option);
            return (
              <button
                key={option}
                type="button"
                disabled={disabled}
                aria-pressed={active}
                onClick={() => onSave(active ? selected.filter((item) => item !== option) : [...selected, option])}
                className={cn(
                  "rounded-sm border px-1.5 py-0.5 text-caption-md-regular",
                  active ? "border-accent-strong bg-accent-subtle text-accent-primary" : "border-subtle text-tertiary"
                )}
              >
                {option}
              </button>
            );
          })}
          {disabled && selected.length === 0 && <span className="text-body-xs-regular text-tertiary">None</span>}
        </div>
      );
    }
    case "user": {
      const ids = Array.isArray(value) ? value.map(String) : [];
      return disabled ? (
        <span className="px-2 text-body-xs-regular text-primary">
          {ids.map((id) => getUserDetails(id)?.display_name ?? "Member").join(", ") || "None"}
        </span>
      ) : (
        <MemberSelect
          value={ids}
          onChange={(next) => onSave(next)}
          projectId={projectId}
          multiple
          variant="select-ghost-md"
          placeholder={`Add ${field.name.toLowerCase()}`}
          showLabel={ids.length <= 1}
          tooltip={{ heading: field.name }}
        />
      );
    }
    default:
      return null;
  }
}

/** The project's custom fields on a work item (including fields imported from Jira). */
export const IssueCustomFields = observer(function IssueCustomFields(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled } = props;
  const { fields } = useProjectCustomFields(workspaceSlug, projectId);
  const { values, mutate } = useIssueCustomFieldValues(workspaceSlug, projectId, issueId);
  const { fetchActivities } = useIssueDetail();

  if (!fields?.length) return null;

  const save = async (field: TCustomField, value: TCustomFieldValue) => {
    try {
      const result = await customFieldService.setValue(workspaceSlug, projectId, issueId, field.id, value);
      await mutate({ ...values, [field.id]: result.value }, { revalidate: false });
      void fetchActivities(workspaceSlug, projectId, issueId);
    } catch (error) {
      void mutate();
      setToast({ type: "error", title: `${field.name} not saved`, message: errorMessage(error) });
    }
  };

  return (
    <>
      {fields.map((field) => (
        <SidebarPropertyListItem key={field.id} icon={PropertiesOutline} label={field.name}>
          <FieldEditor
            field={field}
            value={values?.[field.id] ?? null}
            disabled={disabled}
            projectId={projectId}
            onSave={(value) => void save(field, value)}
          />
        </SidebarPropertyListItem>
      ))}
    </>
  );
});
