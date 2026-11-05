/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Field } from "@makeplane/propel/components/field";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { Popover, PopoverContent, PopoverTrigger } from "@makeplane/propel/components/popover";
import { TextArea, TextAreaGroup } from "@makeplane/propel/components/text-area";
import { Button } from "@makeplane/propel/components/button";
import { ColorSwatchPicker } from "@plane/blocks/common";
import { StateGroupIcon } from "@plane/blocks/icons";
import { EIconSize, STATE_GROUPS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { IState } from "@plane/types";

type TStateForm = {
  data: Partial<IState>;
  onSubmit: (formData: Partial<IState>) => Promise<{ status: string }>;
  onCancel: () => void;
  buttonDisabled: boolean;
  buttonTitle: string;
  /** editing: the status can be moved to another category (Backlog, Unstarted, Started, Completed, Cancelled) */
  showCategory?: boolean;
};

function PopoverButton({ color }: { color?: string }) {
  return (
    <span
      className="group inline-flex h-5 w-5 items-center rounded-sm text-14 font-medium transition-all"
      style={{
        backgroundColor: color ?? "black",
      }}
    />
  );
}

export function StateForm(props: TStateForm) {
  const { data, onSubmit, onCancel, buttonDisabled, buttonTitle, showCategory = false } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [formData, setFromData] = useState<Partial<IState> | undefined>(undefined);
  const [errors, setErrors] = useState<Partial<Record<keyof IState, string>> | undefined>(undefined);

  useEffect(() => {
    if (data && !formData) setFromData(data);
  }, [data, formData]);

  const handleFormData = <T extends keyof IState>(key: T, value: IState[T]) => {
    setFromData((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: "" }));
  };

  const formSubmit = async (event: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
    event.preventDefault();

    const name = formData?.name || undefined;
    if (!formData || !name) {
      let currentErrors: Partial<Record<keyof IState, string>> = {};
      if (!name) currentErrors = { ...currentErrors, name: "Name is required" };
      setErrors(currentErrors);
      return;
    }

    try {
      await onSubmit(formData);
    } catch (error) {
      console.log("error", error);
    }
  };

  return (
    <div className="relative flex space-x-2 rounded-sm bg-surface-1 p-3">
      {/* color */}
      <div className="mt-2 h-full flex-shrink-0">
        <Popover>
          <PopoverTrigger
            render={
              <button
                type="button"
                className="flex items-center justify-center rounded-sm focus:outline-none"
                aria-label={t("aria_labels.color_picker.open")}
              >
                <PopoverButton color={formData?.color} />
              </button>
            }
          />
          <PopoverContent variant="rich" side="bottom" align="start">
            <ColorSwatchPicker value={formData?.color} onChange={(hex) => handleFormData("color", hex)} />
          </PopoverContent>
        </Popover>
      </div>

      <div className="w-full space-y-2">
        {/* title */}
        <Field name="name" invalid={(errors && Boolean(errors.name)) || false}>
          <InputGroup size="2xl">
            <Input
              size="2xl"
              id="name"
              type="text"
              name="name"
              placeholder="Name"
              value={formData?.name}
              onChange={(e) => handleFormData("name", e.target.value)}
              maxLength={100}
              // the inline form opens to type the name right away
              // oxlint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
            />
          </InputGroup>
        </Field>

        {/* description */}
        <Field name="description" invalid={(errors && Boolean(errors.description)) || false}>
          <TextAreaGroup resize="none">
            <TextArea
              size="lg"
              surface="field"
              autoResize
              maxRows={8}
              id="description"
              name="description"
              placeholder="Describe this state for your members."
              value={formData?.description ?? ""}
              onChange={(e) => handleFormData("description", e.target.value)}
            />
          </TextAreaGroup>
        </Field>

        {/* category: which group the status belongs to (drives progress, reports and its icon) */}
        {showCategory && (
          <div className="flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="Category">
            <span className="mr-1 text-caption-md-medium text-tertiary">Category</span>
            {Object.values(STATE_GROUPS).map((group) => (
              <button
                key={group.key}
                type="button"
                role="radio"
                aria-checked={formData?.group === group.key}
                onClick={() => handleFormData("group", group.key)}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-caption-md-medium ${
                  formData?.group === group.key
                    ? "border-accent-strong bg-accent-subtle text-accent-primary"
                    : "border-subtle text-secondary hover:bg-layer-transparent-hover"
                }`}
              >
                <StateGroupIcon stateGroup={group.key} size={EIconSize.SM} />
                {group.label}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center space-x-2">
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label={buttonTitle}
            onClick={formSubmit}
            disabled={buttonDisabled}
          />
          <Button
            type="button"
            variant="secondary"
            size="md"
            stretch="auto"
            label="Cancel"
            disabled={buttonDisabled}
            onClick={onCancel}
          />
        </div>
      </div>
    </div>
  );
}
