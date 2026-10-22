/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
// hooks
import { useProjectCustomFields } from "@/hooks/use-custom-fields";
// services
import type { TCustomField, TCustomFieldType } from "@/services/custom-field.service";
import { CUSTOM_FIELD_TYPE_LABELS, customFieldService } from "@/services/custom-field.service";

type Props = { workspaceSlug: string; projectId: string; isEditable: boolean };

type TDraft = { id?: string; name: string; field_type: TCustomFieldType; description: string; options: string };

const EMPTY: TDraft = { name: "", field_type: "text", description: "", options: "" };

const CONTROL = "w-full rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary";

const errorMessage = (error: unknown, fallback: string) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string" ? error.error : fallback;

const hasOptions = (type: TCustomFieldType) => type === "select" || type === "multi_select";

/** Project settings → Custom fields: the fields this project's work items have, like Jira's custom fields. */
export const CustomFieldsSettings = observer(function CustomFieldsSettings(props: Props) {
  const { workspaceSlug, projectId, isEditable } = props;
  const { fields, mutate } = useProjectCustomFields(workspaceSlug, projectId);
  const [draft, setDraft] = useState<TDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [toDelete, setToDelete] = useState<TCustomField | null>(null);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    const data = {
      name: draft.name.trim(),
      field_type: draft.field_type,
      description: draft.description,
      options: hasOptions(draft.field_type)
        ? draft.options
            .split("\n")
            .map((option) => option.trim())
            .filter(Boolean)
        : [],
    };
    try {
      if (draft.id) await customFieldService.update(workspaceSlug, projectId, draft.id, data);
      else await customFieldService.create(workspaceSlug, projectId, data);
      await mutate();
      setToast({ type: "success", title: draft.id ? "Field updated" : "Field added", message: data.name });
      setDraft(null);
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The field could not be saved.") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {isEditable && !draft && (
        <Button variant="primary" size="md" stretch="auto" label="Add field" onClick={() => setDraft(EMPTY)} />
      )}

      {draft && (
        <form
          className="space-y-3 rounded-lg border border-accent-strong p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1 text-caption-md-medium text-secondary">
              <span>Name</span>
              <InputGroup size="md">
                <Input
                  size="md"
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  placeholder="e.g. Task Type"
                  aria-label="Field name"
                  maxLength={255}
                />
              </InputGroup>
            </div>
            <label className="space-y-1 text-caption-md-medium text-secondary">
              <span>Type</span>
              <select
                className={CONTROL}
                value={draft.field_type}
                onChange={(event) => setDraft({ ...draft, field_type: event.target.value as TCustomFieldType })}
              >
                {Object.entries(CUSTOM_FIELD_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {hasOptions(draft.field_type) && (
            <label className="block space-y-1 text-caption-md-medium text-secondary">
              <span>Options (one per line)</span>
              <textarea
                className={`${CONTROL} min-h-24`}
                value={draft.options}
                onChange={(event) => setDraft({ ...draft, options: event.target.value })}
                placeholder={"Frontend\nBackend\nDesign"}
              />
            </label>
          )}
          <div className="block space-y-1 text-caption-md-medium text-secondary">
            <span>Description (optional)</span>
            <InputGroup size="md">
              <Input
                size="md"
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                placeholder="What is this field for?"
                aria-label="Field description"
              />
            </InputGroup>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" stretch="auto" label="Cancel" onClick={() => setDraft(null)} />
            <Button
              variant="primary"
              size="sm"
              stretch="auto"
              type="submit"
              label={saving ? "Saving…" : draft.id ? "Save field" : "Add field"}
              disabled={saving || !draft.name.trim()}
            />
          </div>
        </form>
      )}

      {fields && fields.length === 0 && !draft && (
        <p className="rounded-md border border-subtle px-4 py-6 text-center text-body-xs-regular text-tertiary">
          No custom fields yet.
        </p>
      )}

      {fields && fields.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {fields.map((field) => (
            <div key={field.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-body-xs-medium text-primary">
                  {field.name}
                  {field.external_source === "jira" && (
                    <span className="ml-2 rounded-sm bg-layer-3 px-1.5 text-caption-sm-regular text-tertiary">
                      from Jira
                    </span>
                  )}
                </p>
                <p className="text-caption-md-regular text-tertiary">
                  {CUSTOM_FIELD_TYPE_LABELS[field.field_type]}
                  {field.options.length > 0 &&
                    ` · ${field.options.slice(0, 6).join(", ")}${field.options.length > 6 ? "…" : ""}`}
                  {field.description && ` · ${field.description}`}
                </p>
              </div>
              {isEditable && (
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    stretch="auto"
                    label="Edit"
                    onClick={() =>
                      setDraft({
                        id: field.id,
                        name: field.name,
                        field_type: field.field_type,
                        description: field.description,
                        options: field.options.join("\n"),
                      })
                    }
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    stretch="auto"
                    label="Delete"
                    onClick={() => setToDelete(field)}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        isOpen={!!toDelete}
        handleClose={() => setToDelete(null)}
        handleSubmit={async () => {
          if (!toDelete) return;
          const field = toDelete;
          setToDelete(null);
          try {
            await customFieldService.remove(workspaceSlug, projectId, field.id);
            await mutate();
          } catch (error) {
            setToast({
              type: "error",
              title: "Error!",
              message: errorMessage(error, "The field could not be deleted."),
            });
          }
        }}
        title={`Delete the ${toDelete?.name ?? ""} field?`}
        content="The field and its value on every work item of this project are removed. This cannot be undone."
        isSubmitting={false}
        primaryButtonText={{ default: "Delete field" }}
      />
    </div>
  );
});
