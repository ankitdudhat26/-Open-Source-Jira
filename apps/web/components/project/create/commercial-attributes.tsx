/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ClipboardEvent } from "react";
import { Controller, useFormContext } from "react-hook-form";
import { Button } from "@makeplane/propel/components/button";
import { Field } from "@makeplane/propel/components/field";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { AddOutline, CloseOutline } from "@makeplane/propel/icons";
// plane imports
import { Select } from "@plane/blocks/select";
import type { TMilestoneFormData, TProject, TProjectType } from "@plane/types";

export const PROJECT_TYPE_OPTIONS: { key: TProjectType; label: string; description: string }[] = [
  { key: "fixed_cost", label: "Fixed Cost", description: "Billed by milestones and deliverables" },
  { key: "dedicated", label: "Dedicated", description: "Dedicated resources for the client" },
  { key: "time_and_material", label: "T&M", description: "Billed on time and material" },
];

export const getProjectTypeLabel = (projectType: TProjectType | undefined) =>
  PROJECT_TYPE_OPTIONS.find((option) => option.key === projectType)?.label;

/** Splits pasted text into one entry per non-empty line. */
const getPastedLines = (event: ClipboardEvent<HTMLInputElement>) =>
  event.clipboardData
    .getData("text")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

function DeliverableLines(props: { value: string[]; onChange: (value: string[]) => void }) {
  const { value, onChange } = props;
  const lines = value.length > 0 ? value : [""];

  const updateLine = (index: number, line: string) =>
    onChange(lines.map((current, i) => (i === index ? line : current)));
  const removeLine = (index: number) => onChange(lines.filter((_, i) => i !== index));

  return (
    <div className="space-y-2">
      {lines.map((line, index) => (
        // rows are plain controlled inputs without an identity of their own
        // oxlint-disable-next-line react/no-array-index-key
        <div key={index} className="flex items-center gap-2">
          <span className="w-5 shrink-0 text-right text-caption-sm-regular text-tertiary">{index + 1}.</span>
          <div className="flex-1">
            <InputGroup size="md">
              <Input
                size="md"
                type="text"
                value={line}
                aria-label={`Deliverable ${index + 1}`}
                placeholder="Deliverable"
                maxLength={255}
                onChange={(e) => updateLine(index, e.target.value)}
                onPaste={(e) => {
                  const pasted = getPastedLines(e);
                  if (pasted.length < 2) return;
                  // Pasting several lines adds one deliverable per line
                  e.preventDefault();
                  onChange([...lines.slice(0, index), ...pasted, ...lines.slice(index + 1)].filter(Boolean));
                }}
              />
            </InputGroup>
          </div>
          <IconButton
            variant="ghost"
            size="sm"
            icon={<CloseOutline />}
            aria-label="Remove deliverable"
            disabled={lines.length === 1 && !line}
            onClick={() => removeLine(index)}
          />
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        stretch="auto"
        icon={<AddOutline />}
        label="Add deliverable"
        onClick={() => onChange([...lines, ""])}
      />
    </div>
  );
}

function MilestoneRows(props: {
  value: TMilestoneFormData[];
  onChange: (value: TMilestoneFormData[]) => void;
  invalidRows: number[];
}) {
  const { value, onChange, invalidRows } = props;
  const rows = value.length > 0 ? value : [{ name: "", amount: null }];

  const updateRow = (index: number, data: Partial<TMilestoneFormData>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...data } : row)));
  const removeRow = (index: number) => onChange(rows.filter((_, i) => i !== index));

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-caption-sm-medium text-tertiary">
        <span className="w-5 shrink-0" />
        <span className="flex-1">Name</span>
        <span className="w-36 shrink-0">Amount</span>
        <span className="w-7 shrink-0" />
      </div>
      {rows.map((row, index) => (
        // rows are plain controlled inputs without an identity of their own
        // oxlint-disable-next-line react/no-array-index-key
        <div key={index} className="flex items-start gap-2">
          <span className="mt-1.5 w-5 shrink-0 text-right text-caption-sm-regular text-tertiary">{index + 1}.</span>
          <div className="flex-1">
            <Field invalid={invalidRows.includes(index)}>
              <InputGroup size="md">
                <Input
                  size="md"
                  type="text"
                  value={row.name}
                  aria-label={`Milestone ${index + 1} name`}
                  placeholder="Milestone name"
                  maxLength={255}
                  onChange={(e) => updateRow(index, { name: e.target.value })}
                />
              </InputGroup>
            </Field>
          </div>
          <div className="w-36 shrink-0">
            <InputGroup size="md">
              <Input
                size="md"
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                value={row.amount ?? ""}
                aria-label={`Milestone ${index + 1} amount`}
                placeholder="0.00"
                onChange={(e) => updateRow(index, { amount: e.target.value === "" ? null : e.target.value })}
              />
            </InputGroup>
          </div>
          <IconButton
            variant="ghost"
            size="sm"
            icon={<CloseOutline />}
            aria-label="Remove milestone"
            disabled={rows.length === 1 && !row.name && !row.amount}
            onClick={() => removeRow(index)}
          />
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        stretch="auto"
        icon={<AddOutline />}
        label="Add milestone"
        onClick={() => onChange([...rows, { name: "", amount: null }])}
      />
    </div>
  );
}

/** Rows that have an amount but no name. */
export const getInvalidMilestoneRows = (milestones: TMilestoneFormData[] | undefined) =>
  (milestones ?? []).flatMap((row, index) => (!row.name.trim() && row.amount ? [index] : []));

/** EmPro Id, project type and — for fixed cost projects — the deliverables and milestones of the project. */
export function ProjectCommercialAttributes() {
  const {
    control,
    watch,
    formState: { errors },
  } = useFormContext<TProject>();
  const projectType = watch("project_type");
  const isFixedCost = projectType === "fixed_cost";

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-x-2 gap-y-3 md:grid-cols-2">
        <Controller
          control={control}
          name="empro_id"
          rules={{ maxLength: { value: 255, message: "EmPro Id should be less than 255 characters" } }}
          render={({ field: { value, onChange } }) => (
            <Field name="empro_id" invalid={Boolean(errors.empro_id)}>
              <label htmlFor="empro_id" className="mb-1 block text-caption-md-medium text-secondary">
                EmPro Id
              </label>
              <InputGroup size="lg">
                <Input
                  size="lg"
                  id="empro_id"
                  name="empro_id"
                  type="text"
                  value={value ?? ""}
                  onChange={onChange}
                  placeholder="EmPro Id"
                />
              </InputGroup>
              <span className="text-11 text-danger-primary">{errors?.empro_id?.message}</span>
            </Field>
          )}
        />
        <Controller
          control={control}
          name="project_type"
          rules={{ required: "Project type is required" }}
          render={({ field: { value, onChange } }) => {
            const current = PROJECT_TYPE_OPTIONS.find((option) => option.key === value);
            return (
              <div>
                <span className="mb-1 block text-caption-md-medium text-secondary">Project Type</span>
                <Select<(typeof PROJECT_TYPE_OPTIONS)[number]>
                  getValues={() => PROJECT_TYPE_OPTIONS}
                  value={current ?? null}
                  onChange={(key) => onChange(key)}
                  getOptionValue={(option) => option.key}
                  getOptionLabel={(option) => option.label}
                  getOptionDescription={(option) => option.description}
                  placeholder="Select project type"
                  showSearch={false}
                  pinSelected={false}
                  estimateItemSize={56}
                >
                  <Select.Trigger<(typeof PROJECT_TYPE_OPTIONS)[number]> variant="pill-md">
                    {(options) => (
                      <span className="truncate">{options[0] ? options[0].label : "Select project type"}</span>
                    )}
                  </Select.Trigger>
                </Select>
                <span className="block text-11 text-danger-primary">{errors?.project_type?.message}</span>
              </div>
            );
          }}
        />
      </div>

      {isFixedCost && (
        <>
          <div>
            <h4 className="mb-2 text-body-sm-medium text-primary">Deliverables</h4>
            <Controller
              control={control}
              name="deliverables"
              render={({ field: { value, onChange } }) => <DeliverableLines value={value ?? []} onChange={onChange} />}
            />
          </div>
          <div>
            <h4 className="mb-2 text-body-sm-medium text-primary">Milestones</h4>
            <Controller
              control={control}
              name="milestones"
              rules={{
                validate: (value) =>
                  getInvalidMilestoneRows(value).length === 0 || "Every milestone with an amount needs a name",
              }}
              render={({ field: { value, onChange } }) => (
                <MilestoneRows
                  value={value ?? []}
                  onChange={onChange}
                  invalidRows={errors.milestones ? getInvalidMilestoneRows(value) : []}
                />
              )}
            />
            <span className="text-11 text-danger-primary">{errors?.milestones?.message}</span>
          </div>
        </>
      )}
    </div>
  );
}
