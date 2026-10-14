/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import { mutate } from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Dialog, DialogContent } from "@makeplane/propel/components/dialog";
import { Field } from "@makeplane/propel/components/field";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { TextArea, TextAreaGroup } from "@makeplane/propel/components/text-area";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import type { TDeliverable, TDeliverablePayload, TMilestone } from "@plane/types";
// hooks
import { PROJECT_DELIVERABLES, PROJECT_MILESTONES, projectMilestoneService } from "@/hooks/use-project-milestones";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
  milestones: TMilestone[];
  data?: TDeliverable;
};

type TDeliverableForm = {
  name: string;
  description: string;
  milestone_id: string | null;
};

const getDefaultValues = (data?: TDeliverable): TDeliverableForm => ({
  name: data?.name ?? "",
  description: data?.description ?? "",
  milestone_id: data?.milestone_id ?? null,
});

export function DeliverableFormModal(props: Props) {
  const { isOpen, onClose, workspaceSlug, projectId, milestones, data } = props;
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<TDeliverableForm>({ defaultValues: getDefaultValues(data) });

  useEffect(() => {
    if (isOpen) reset(getDefaultValues(data));
  }, [isOpen, data, reset]);

  const onSubmit = async (formData: TDeliverableForm) => {
    const payload: TDeliverablePayload = { ...formData, name: formData.name.trim() };
    try {
      if (data) await projectMilestoneService.updateDeliverable(workspaceSlug, projectId, data.id, payload);
      else await projectMilestoneService.createDeliverable(workspaceSlug, projectId, payload);
      await Promise.all([mutate(PROJECT_DELIVERABLES(projectId)), mutate(PROJECT_MILESTONES(projectId))]);
      setToast({ type: "success", title: "Success!", message: `Deliverable ${data ? "updated" : "added"}.` });
      onClose();
    } catch {
      setToast({ type: "error", title: "Error!", message: "Deliverable could not be saved." });
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
      <DialogContent size="md" aria-label={data ? "Update deliverable" : "Add deliverable"}>
        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-4 p-5">
            <h3 className="text-18 font-medium text-secondary">{data ? "Update deliverable" : "Add deliverable"}</h3>
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
                        type="text"
                        value={value}
                        onChange={onChange}
                        placeholder="Deliverable"
                      />
                    </InputGroup>
                  </Field>
                )}
              />
              <span className="text-11 text-danger-primary">{errors.name?.message}</span>
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
                      maxRows={6}
                      id="description"
                      value={value}
                      onChange={onChange}
                      placeholder="Description"
                    />
                  </TextAreaGroup>
                </Field>
              )}
            />
            <Controller
              control={control}
              name="milestone_id"
              render={({ field: { value, onChange } }) => (
                <Select<TMilestone>
                  getValues={() => milestones}
                  value={milestones.find((milestone) => milestone.id === value) ?? null}
                  onChange={(milestoneId) => onChange(milestoneId === value ? null : milestoneId)}
                  getOptionValue={(milestone) => milestone.id}
                  getOptionLabel={(milestone) =>
                    milestone.code ? `${milestone.code} · ${milestone.name}` : milestone.name
                  }
                  placeholder="Milestone"
                  showSearch={milestones.length > 8}
                  pinSelected={false}
                >
                  <Select.Trigger<TMilestone> variant="pill-md">
                    {(selected) => (
                      <span className="truncate">{selected[0] ? selected[0].name : "Select milestone"}</span>
                    )}
                  </Select.Trigger>
                </Select>
              )}
            />
          </div>
          <div className="flex items-center justify-end gap-2 border-t-[0.5px] border-subtle px-5 py-4">
            <Button variant="secondary" size="md" stretch="auto" label="Cancel" onClick={onClose} />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              type="submit"
              loading={isSubmitting}
              label={data ? "Update deliverable" : "Add deliverable"}
            />
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
