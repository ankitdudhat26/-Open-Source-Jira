/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { CloseOutline, LoadingOutline } from "@makeplane/propel/icons";
// plane imports
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { IState, TStateOperationsCallbacks } from "@plane/types";
import { cn } from "@plane/utils";
// components
import { StateSelect } from "@/components/dropdowns/state/state-select";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { usePlatformOS } from "@/hooks/use-platform-os";

type TStateDelete = {
  totalStates: number;
  state: IState;
  deleteStateCallback: TStateOperationsCallbacks["deleteState"];
};

export const StateDelete = observer(function StateDelete(props: TStateDelete) {
  const { totalStates, state, deleteStateCallback } = props;
  // plane hooks
  const { t } = useTranslation();
  // hooks
  const { isMobile } = usePlatformOS();
  // states
  const [isDeleteModal, setIsDeleteModal] = useState(false);
  const [isDelete, setIsDelete] = useState(false);
  // derived values
  const isDeleteDisabled = !!state.default || totalStates === 1;
  // where its work items go: another status of the same category, else the default one
  const { getProjectStates } = useProjectState();
  const otherStates = (getProjectStates(state.project_id) ?? []).filter((item) => item.id !== state.id);
  const suggested =
    otherStates.find((item) => item.group === state.group) ??
    otherStates.find((item) => item.default) ??
    otherStates[0];
  const [moveTo, setMoveTo] = useState<string | undefined>(undefined);
  const target = moveTo ?? suggested?.id;

  const handleDeleteState = async () => {
    if (isDeleteDisabled) return;

    setIsDelete(true);

    try {
      await deleteStateCallback(state.id, target);
      setIsDelete(false);
      setIsDeleteModal(false);
    } catch (error) {
      const errorStatus = error as { status?: number; data?: { error?: string } };
      setToast({
        type: "error",
        title: "Error!",
        message:
          errorStatus?.status === 400 && errorStatus.data?.error
            ? errorStatus.data.error
            : "State could not be deleted. Please try again.",
      });
      setIsDelete(false);
    }
  };

  return (
    <>
      <ConfirmDialog
        handleClose={() => setIsDeleteModal(false)}
        handleSubmit={handleDeleteState}
        isSubmitting={isDelete}
        isOpen={isDeleteModal}
        title="Delete State"
        content={
          <div className="flex flex-col gap-3">
            <p>
              Delete the status <span className="font-medium text-primary">{state?.name}</span>? Its moves in the
              workflow are removed too.
            </p>
            <div className="flex flex-col gap-1.5">
              <span className="text-body-xs-medium text-primary">Move its work items to</span>
              <div className="w-64">
                <StateSelect
                  projectId={state.project_id}
                  value={target ?? null}
                  onChange={(stateId) => setMoveTo(stateId)}
                  variant="select-md"
                  placeholder="Choose a status"
                  excludeStateIds={[state.id]}
                />
              </div>
              <span className="text-caption-md-regular text-tertiary">
                Every work item in {state?.name} (also archived ones) moves there before it is deleted.
              </span>
            </div>
          </div>
        }
      />

      <Tooltip
        label={
          state.default ? "Cannot delete the default state." : totalStates === 1 ? `Cannot have an empty group.` : ``
        }
        layout="stacked"
        disabled={!isDeleteDisabled || isMobile}
      >
        {/* Not `disabled`: a disabled button would never show the tooltip that explains why. */}
        <IconButton
          variant="ghost"
          size="xs"
          aria-label={t("common.delete")}
          aria-disabled={isDeleteDisabled}
          icon={
            isDelete ? (
              <Icon icon={<LoadingOutline className="animate-spin text-secondary" />} />
            ) : (
              <Icon icon={<CloseOutline className={cn({ "text-danger-primary": !isDeleteDisabled })} />} />
            )
          }
          onClick={() => {
            if (isDeleteDisabled) return;
            setIsDeleteModal(true);
          }}
        />
      </Tooltip>
    </>
  );
});
