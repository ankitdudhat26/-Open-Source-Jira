/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { Controller, useForm } from "react-hook-form";
import { mutate } from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Dialog, DialogContent } from "@makeplane/propel/components/dialog";
import { Field } from "@makeplane/propel/components/field";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { TextArea, TextAreaGroup } from "@makeplane/propel/components/text-area";
import { setToast } from "@plane/blocks/toast";
import type { TMilestone, TMilestonePayload } from "@plane/types";
// components
import { ModuleSelect } from "@/components/dropdowns/module/module-select";
// hooks
import { PROJECT_MILESTONES, projectMilestoneService } from "@/hooks/use-project-milestones";

type TMilestoneForm = {
  name: string;
  amount: string;
  payment_percentage: string;
  description: string;
  module_ids: string[];
};

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
  data?: TMilestone;
};

const getDefaultValues = (data?: TMilestone): TMilestoneForm => ({
  name: data?.name ?? "",
  amount: data?.amount ?? "",
  payment_percentage: data?.payment_percentage ?? "",
  description: data?.description ?? "",
  module_ids: data?.module_ids ?? [],
});

export const MilestoneFormModal = observer(function MilestoneFormModal(props: Props) {
  const { isOpen, onClose, workspaceSlug, projectId, data } = props;
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<TMilestoneForm>({ defaultValues: getDefaultValues(data) });

  useEffect(() => {
    if (isOpen) reset(getDefaultValues(data));
  }, [isOpen, data, reset]);

  const onSubmit = async (formData: TMilestoneForm) => {
    const payload: TMilestonePayload = {
      name: formData.name.trim(),
      amount: formData.amount === "" ? null : formData.amount,
      payment_percentage: formData.payment_percentage === "" ? null : formData.payment_percentage,
      description: formData.description,
      module_ids: formData.module_ids,
    };
    try {
      if (data) await projectMilestoneService.updateMilestone(workspaceSlug, projectId, data.id, payload);
      else await projectMilestoneService.createMilestone(workspaceSlug, projectId, payload);
      await mutate(PROJECT_MILESTONES(projectId));
      setToast({ type: "success", title: "Success!", message: `Milestone ${data ? "updated" : "created"}.` });
      onClose();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: "Error!", message: message ?? "Milestone could not be saved." });
    }
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      disablePointerDismissal
    >
      <DialogContent size="md" aria-label={data ? "Update milestone" : "Add milestone"}>
        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-4 p-5">
            <h3 className="text-18 font-medium text-secondary">{data ? "Update milestone" : "Add milestone"}</h3>
            <div>
              <Controller
                control={control}
                name="name"
                rules={{
                  validate: (value) => value.trim() !== "" || "Name is required",
                  maxLength: { value: 255, message: "Name should be less than 255 characters" },
                }}
                render={({ field: { value, onChange } }) => (
                  <Field name="name" invalid={Boolean(errors.name)}>
                    <InputGroup size="xl">
                      <Input
                        size="xl"
                        id="name"
                        name="name"
                        type="text"
                        value={value}
                        onChange={onChange}
                        placeholder="Milestone name"
                      />
                    </InputGroup>
                  </Field>
                )}
              />
              <span className="text-11 text-danger-primary">{errors.name?.message}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="amount" className="mb-1 block text-caption-md-medium text-secondary">
                  Amount
                </label>
                <Controller
                  control={control}
                  name="amount"
                  rules={{ validate: (value) => value === "" || Number(value) >= 0 || "Amount cannot be negative" }}
                  render={({ field: { value, onChange } }) => (
                    <Field name="amount" invalid={Boolean(errors.amount)}>
                      <InputGroup size="lg">
                        <Input
                          size="lg"
                          id="amount"
                          type="number"
                          min={0}
                          step="0.01"
                          inputMode="decimal"
                          value={value}
                          onChange={onChange}
                          placeholder="0.00"
                        />
                      </InputGroup>
                    </Field>
                  )}
                />
                <span className="text-11 text-danger-primary">{errors.amount?.message}</span>
              </div>
              <div>
                <label htmlFor="payment_percentage" className="mb-1 block text-caption-md-medium text-secondary">
                  Payment %
                </label>
                <Controller
                  control={control}
                  name="payment_percentage"
                  rules={{
                    validate: (value) =>
                      value === "" || (Number(value) >= 0 && Number(value) <= 100) || "Enter a value from 0 to 100",
                  }}
                  render={({ field: { value, onChange } }) => (
                    <Field name="payment_percentage" invalid={Boolean(errors.payment_percentage)}>
                      <InputGroup size="lg">
                        <Input
                          size="lg"
                          id="payment_percentage"
                          type="number"
                          min={0}
                          max={100}
                          step="0.01"
                          inputMode="decimal"
                          value={value}
                          onChange={onChange}
                          placeholder="0"
                        />
                      </InputGroup>
                    </Field>
                  )}
                />
                <span className="text-11 text-danger-primary">{errors.payment_percentage?.message}</span>
              </div>
            </div>
            <Controller
              control={control}
              name="description"
              render={({ field: { value, onChange } }) => (
                <Field name="description">
                  <TextAreaGroup resize="none">
                    <TextArea
                      size="lg"
                      surface="field"
                      autoResize
                      maxRows={8}
                      id="description"
                      name="description"
                      value={value}
                      onChange={onChange}
                      placeholder="Scope / acceptance criteria"
                    />
                  </TextAreaGroup>
                </Field>
              )}
            />
            <div>
              <span className="mb-1 block text-caption-md-medium text-secondary">
                Modules delivered in this milestone
              </span>
              <Controller
                control={control}
                name="module_ids"
                render={({ field: { value, onChange } }) => (
                  <ModuleSelect
                    multiple
                    projectId={projectId}
                    value={value}
                    onChange={onChange}
                    placeholder="Select modules"
                    variant="pill-md"
                  />
                )}
              />
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 border-t-[0.5px] border-subtle px-5 py-4">
            <Button variant="secondary" size="md" stretch="auto" label="Cancel" onClick={onClose} />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              type="submit"
              loading={isSubmitting}
              label={
                data ? (isSubmitting ? "Updating" : "Update milestone") : isSubmitting ? "Adding" : "Add milestone"
              }
            />
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
});
