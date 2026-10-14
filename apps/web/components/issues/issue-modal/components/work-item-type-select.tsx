/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import type { Control, UseFormSetValue } from "react-hook-form";
import { Controller } from "react-hook-form";
// plane imports
import { Select } from "@plane/blocks/select";
import type { TIssue, TWorkItemType } from "@plane/types";
// hooks
import { useProjectWorkItemTypes } from "@/hooks/use-project-milestones";

type Props = {
  control: Control<TIssue>;
  setValue: UseFormSetValue<TIssue>;
  workspaceSlug: string;
  projectId: string | null;
  typeId: string | null | undefined;
  isEditing: boolean;
  handleFormChange: () => void;
};

export function WorkItemTypeDot(props: { color: string }) {
  return <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: props.color }} />;
}

/** Feature / Task / Bug selector of the create work item form. New work items start as the default type (Task). */
export const WorkItemTypeSelect = observer(function WorkItemTypeSelect(props: Props) {
  const { control, setValue, workspaceSlug, projectId, typeId, isEditing, handleFormChange } = props;
  const { workItemTypes, defaultWorkItemType, getTypeById } = useProjectWorkItemTypes(workspaceSlug, projectId);

  useEffect(() => {
    if (!workItemTypes || isEditing) return;
    // the selected type has to belong to the selected project
    if (typeId && getTypeById(typeId)) return;
    if (defaultWorkItemType) setValue("type_id", defaultWorkItemType.id);
  }, [workItemTypes, defaultWorkItemType, typeId, isEditing, getTypeById, setValue]);

  if (!workItemTypes) return null;

  return (
    <Controller
      control={control}
      name="type_id"
      render={({ field: { value, onChange } }) => (
        <Select<TWorkItemType>
          getValues={() => workItemTypes}
          value={getTypeById(value) ?? null}
          onChange={(selectedTypeId) => {
            onChange(selectedTypeId);
            // a feature is not created under another work item
            if (getTypeById(selectedTypeId)?.key === "feature") setValue("parent_id", null);
            handleFormChange();
          }}
          getOptionValue={(type) => type.id}
          getOptionLabel={(type) => type.name}
          getOptionDescription={(type) => type.description}
          getOptionIcon={(type) => <WorkItemTypeDot color={type.color} />}
          placeholder="Type"
          showSearch={false}
          pinSelected={false}
          estimateItemSize={56}
        >
          <Select.Trigger<TWorkItemType>
            variant="pill-md"
            prependIcon={(types) => (types[0] ? <WorkItemTypeDot color={types[0].color} /> : undefined)}
          >
            {(types) => <span className="truncate">{types[0] ? types[0].name : "Type"}</span>}
          </Select.Trigger>
        </Select>
      )}
    />
  );
});
