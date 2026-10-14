/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { mutate } from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { AddOutline, DeleteOutline, EditOutline, MilestoneOutline } from "@makeplane/propel/icons";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TDeliverable } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useUserPermissions } from "@/hooks/store/user";
import {
  PROJECT_DELIVERABLES,
  PROJECT_MILESTONES,
  projectMilestoneService,
  useProjectDeliverables,
  useProjectMilestones,
} from "@/hooks/use-project-milestones";
// local imports
import { DeliverableFormModal } from "./deliverable-form-modal";

type Props = {
  workspaceSlug: string;
  projectId: string;
};

// ID | Deliverable | Description | Milestone | actions
const GRID = "grid grid-cols-[80px_minmax(220px,1.2fr)_minmax(240px,2fr)_220px_76px] items-center";

/** Deliverables of the project and the milestone each one is handed over at. */
export const DeliverablesTable = observer(function DeliverablesTable(props: Props) {
  const { workspaceSlug, projectId } = props;
  // states
  const [modal, setModal] = useState<{ isOpen: boolean; data?: TDeliverable }>({ isOpen: false });
  const [deleteTarget, setDeleteTarget] = useState<TDeliverable | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  // hooks
  const { allowPermissions } = useUserPermissions();
  const { milestones } = useProjectMilestones(workspaceSlug, projectId);
  const { deliverables, isLoading } = useProjectDeliverables(workspaceSlug, projectId);
  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const milestoneOrder = new Map((milestones ?? []).map((milestone, index) => [milestone.id, index]));
  // in milestone order, deliverables without a milestone last
  // copy is sorted, the source array is left untouched (toSorted needs ES2023)
  // oxlint-disable-next-line unicorn/no-array-sort
  const sorted = [...(deliverables ?? [])].sort(
    (a, b) =>
      (milestoneOrder.get(a.milestone_id ?? "") ?? Number.MAX_SAFE_INTEGER) -
        (milestoneOrder.get(b.milestone_id ?? "") ?? Number.MAX_SAFE_INTEGER) || a.sort_order - b.sort_order
  );

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await projectMilestoneService.deleteDeliverable(workspaceSlug, projectId, deleteTarget.id);
      await Promise.all([mutate(PROJECT_DELIVERABLES(projectId)), mutate(PROJECT_MILESTONES(projectId))]);
      setDeleteTarget(null);
    } catch {
      setToast({ type: "error", title: "Error!", message: "Deliverable could not be deleted." });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex items-center gap-2 border-b border-subtle px-page-x py-2.5">
        <span className="text-caption-sm-regular text-tertiary">Deliverables</span>
        <span className="text-body-xs-medium text-primary">{deliverables?.length ?? 0}</span>
        {isAdmin && (
          <div className="ml-auto">
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              icon={<AddOutline />}
              label="Add deliverable"
              onClick={() => setModal({ isOpen: true })}
            />
          </div>
        )}
      </div>
      <div className="vertical-scrollbar horizontal-scrollbar scrollbar-md min-h-0 flex-1 overflow-auto">
        <div role="table" aria-label="Deliverables" className="min-w-[900px]">
          <div
            role="row"
            className={cn(
              GRID,
              "sticky top-0 z-10 border-b border-subtle bg-surface-1 py-2 pl-page-x text-caption-sm-medium text-tertiary"
            )}
          >
            <span>ID</span>
            <span>Deliverable</span>
            <span>Description</span>
            <span>Milestone</span>
            <span />
          </div>
          {isLoading && !deliverables ? (
            <div className="px-page-x py-6 text-body-xs-regular text-tertiary">Loading deliverables…</div>
          ) : sorted.length === 0 ? (
            <div className="px-page-x py-6 text-body-xs-regular text-tertiary">
              No deliverables yet. Import the SOW or add them manually.
            </div>
          ) : (
            sorted.map((deliverable) => {
              const milestone = milestones?.find((item) => item.id === deliverable.milestone_id);
              return (
                <div
                  key={deliverable.id}
                  role="row"
                  className={cn(
                    GRID,
                    "border-b border-subtle py-2 pl-page-x text-body-xs-regular hover:bg-layer-transparent-hover"
                  )}
                >
                  <span className="text-caption-md-medium text-secondary">{deliverable.code || "—"}</span>
                  <span className="truncate pr-3 text-primary" title={deliverable.name}>
                    {deliverable.name}
                  </span>
                  <span className="truncate pr-3 text-secondary" title={deliverable.description}>
                    {deliverable.description || "—"}
                  </span>
                  <span className="flex min-w-0 items-center gap-1.5 pr-3">
                    {milestone ? (
                      <>
                        <MilestoneOutline className="size-3.5 shrink-0 text-tertiary" />
                        <span className="truncate text-secondary">
                          {milestone.code ? `${milestone.code} · ${milestone.name}` : milestone.name}
                        </span>
                      </>
                    ) : (
                      <span className="text-placeholder">No milestone</span>
                    )}
                  </span>
                  <span className="flex justify-end gap-0.5 pr-2">
                    {isAdmin && (
                      <>
                        <IconButton
                          variant="ghost"
                          size="sm"
                          icon={<EditOutline />}
                          aria-label={`Edit ${deliverable.name}`}
                          onClick={() => setModal({ isOpen: true, data: deliverable })}
                        />
                        <IconButton
                          variant="ghost"
                          size="sm"
                          icon={<DeleteOutline />}
                          aria-label={`Delete ${deliverable.name}`}
                          onClick={() => setDeleteTarget(deliverable)}
                        />
                      </>
                    )}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
      <DeliverableFormModal
        isOpen={modal.isOpen}
        data={modal.data}
        milestones={milestones ?? []}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        onClose={() => setModal({ isOpen: false })}
      />
      <ConfirmDialog
        isOpen={!!deleteTarget}
        handleClose={() => setDeleteTarget(null)}
        handleSubmit={handleDelete}
        isSubmitting={isDeleting}
        title="Delete deliverable"
        content={
          <>
            Are you sure you want to delete <span className="font-medium text-primary">{deleteTarget?.name}</span>?
          </>
        }
      />
    </div>
  );
});
