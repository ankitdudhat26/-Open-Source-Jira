/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { mutate } from "swr";
// plane imports
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { IconButton } from "@makeplane/propel/components/icon-button";
import {
  AddOutline,
  ChevronDownOutline,
  ChevronRightOutline,
  DeleteOutline,
  EditOutline,
  FileOutline,
  ModuleOutline,
  TickCircleOutline,
} from "@makeplane/propel/icons";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TMilestone } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useModule } from "@/hooks/store/use-module";
import { useUserPermissions } from "@/hooks/store/user";
import {
  PROJECT_DELIVERABLES,
  PROJECT_MILESTONES,
  projectMilestoneService,
  useProjectDeliverables,
  useProjectMilestones,
} from "@/hooks/use-project-milestones";
// local imports
import {
  MILESTONE_STATUS_LABEL,
  formatAmount,
  formatPercentage,
  getMilestoneProgress,
  getMilestoneStatus,
} from "./helper";
import { MilestoneFormModal } from "./milestone-form-modal";

type Props = {
  workspaceSlug: string;
  projectId: string;
  /** Opens the Work items tab (milestone -> module -> feature -> task). */
  onOpenWorkItems?: () => void;
};

const STATUS_BADGE_VARIANT = {
  completed: "success",
  in_progress: "brand",
  not_started: "neutral",
} as const;

// chevron | ID | Milestone | Status | Progress | Modules | Deliverables | Amount | Payment | actions
export const MILESTONE_GRID =
  "grid grid-cols-[36px_64px_minmax(220px,1fr)_120px_220px_80px_100px_120px_80px_76px] items-center";

function ProgressBar(props: { value: number; isComplete?: boolean; className?: string }) {
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-full bg-layer-3", props.className)}>
      <div
        className={cn("h-full rounded-full", props.isComplete ? "bg-success-primary" : "bg-accent-primary")}
        style={{ width: `${props.value}%` }}
      />
    </div>
  );
}

/** Milestones of the project as an expandable table: each row opens its scope, modules and deliverables. */
export const MilestonesRoot = observer(function MilestonesRoot(props: Props) {
  const { workspaceSlug, projectId, onOpenWorkItems } = props;
  // states
  const [milestoneModal, setMilestoneModal] = useState<{ isOpen: boolean; data?: TMilestone }>({ isOpen: false });
  const [deleteTarget, setDeleteTarget] = useState<TMilestone | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // store hooks
  const { getModuleById, fetchModules } = useModule();
  const { allowPermissions } = useUserPermissions();
  const { milestones, isLoading } = useProjectMilestones(workspaceSlug, projectId);
  const { deliverables } = useProjectDeliverables(workspaceSlug, projectId);
  useSWR(`PROJECT_MODULES_FOR_MILESTONES_${projectId}`, () => fetchModules(workspaceSlug, projectId), {
    revalidateOnFocus: false,
  });
  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const totalAmount = (milestones ?? []).reduce((sum, milestone) => sum + Number(milestone.amount ?? 0), 0);
  const totalPercentage = (milestones ?? []).reduce(
    (sum, milestone) => sum + Number(milestone.payment_percentage ?? 0),
    0
  );
  const completedCount = (milestones ?? []).filter((milestone) => milestone.is_completed).length;

  const toggle = (milestoneId: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(milestoneId)) next.delete(milestoneId);
      else next.add(milestoneId);
      return next;
    });

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await projectMilestoneService.deleteMilestone(workspaceSlug, projectId, deleteTarget.id);
      await Promise.all([mutate(PROJECT_MILESTONES(projectId)), mutate(PROJECT_DELIVERABLES(projectId))]);
      setToast({ type: "success", title: "Success!", message: `${deleteTarget.name} deleted.` });
      setDeleteTarget(null);
    } catch {
      setToast({ type: "error", title: "Error!", message: "Could not delete. Please try again." });
    } finally {
      setIsDeleting(false);
    }
  };

  const renderDetails = (milestone: TMilestone) => {
    const milestoneDeliverables = (deliverables ?? []).filter((d) => d.milestone_id === milestone.id);
    return (
      <div className="grid gap-6 border-b border-subtle bg-layer-1 py-4 pr-4 pl-[100px] md:grid-cols-3">
        <div>
          <div className="mb-1.5 text-caption-sm-medium text-tertiary">Scope / acceptance criteria</div>
          <p className="text-body-xs-regular whitespace-pre-line text-secondary">
            {milestone.description || "No scope added."}
          </p>
          {onOpenWorkItems && milestone.total_issues > 0 && (
            <button
              type="button"
              className="mt-3 text-caption-md-medium text-accent-primary hover:underline"
              onClick={onOpenWorkItems}
            >
              View {milestone.total_issues} work items
            </button>
          )}
        </div>
        <div>
          <div className="mb-1.5 text-caption-sm-medium text-tertiary">Modules</div>
          {milestone.modules.length === 0 ? (
            <div className="text-caption-sm-regular text-placeholder">No modules linked</div>
          ) : (
            <ul className="space-y-2">
              {milestone.modules.map((moduleProgress) => {
                const module = getModuleById(moduleProgress.module_id);
                const value = moduleProgress.total_issues
                  ? Math.round((moduleProgress.done_issues / moduleProgress.total_issues) * 100)
                  : 0;
                return (
                  <li key={moduleProgress.module_id}>
                    <div className="flex items-center gap-2">
                      {moduleProgress.is_completed ? (
                        <TickCircleOutline className="size-3.5 shrink-0 text-success-primary" />
                      ) : (
                        <ModuleOutline className="size-3.5 shrink-0 text-tertiary" />
                      )}
                      <Link
                        href={`/${workspaceSlug}/projects/${projectId}/modules/${moduleProgress.module_id}`}
                        className="min-w-0 flex-1 truncate text-body-xs-regular text-primary hover:underline"
                      >
                        {module?.name ?? "Module"}
                      </Link>
                      <span className="shrink-0 text-caption-sm-regular text-tertiary">
                        {moduleProgress.done_issues} / {moduleProgress.total_issues}
                      </span>
                    </div>
                    <ProgressBar value={value} isComplete={moduleProgress.is_completed} className="mt-1 ml-[22px]" />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div>
          <div className="mb-1.5 text-caption-sm-medium text-tertiary">Deliverables</div>
          {milestoneDeliverables.length === 0 ? (
            <div className="text-caption-sm-regular text-placeholder">No deliverables</div>
          ) : (
            <ul className="space-y-1.5">
              {milestoneDeliverables.map((deliverable) => (
                <li key={deliverable.id} className="flex items-start gap-2">
                  <FileOutline className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
                  <div className="min-w-0">
                    <div className="text-body-xs-regular text-primary">
                      {deliverable.code && <span className="mr-1.5 text-tertiary">{deliverable.code}</span>}
                      {deliverable.name}
                    </div>
                    {deliverable.description && (
                      <div className="text-caption-sm-regular text-tertiary">{deliverable.description}</div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-full w-full flex-col">
      {/* Summary + actions */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-subtle px-page-x py-2.5">
        {[
          { label: "Milestones", value: String(milestones?.length ?? 0) },
          { label: "Completed", value: `${completedCount} / ${milestones?.length ?? 0}` },
          { label: "Total amount", value: formatAmount(totalAmount) },
          { label: "Total payment", value: formatPercentage(totalPercentage) },
        ].map((item) => (
          <div key={item.label} className="flex items-baseline gap-1.5">
            <span className="text-caption-sm-regular text-tertiary">{item.label}</span>
            <span className="text-body-xs-medium text-primary">{item.value}</span>
          </div>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            stretch="auto"
            label="Expand all"
            onClick={() => setExpanded(new Set((milestones ?? []).map((m) => m.id)))}
          />
          <Button
            variant="secondary"
            size="sm"
            stretch="auto"
            label="Collapse all"
            onClick={() => setExpanded(new Set())}
          />
        </div>
      </div>

      <div className="vertical-scrollbar horizontal-scrollbar scrollbar-md min-h-0 flex-1 overflow-auto">
        <div role="table" aria-label="Milestones" className="min-w-[1080px]">
          <div
            role="row"
            className={cn(
              MILESTONE_GRID,
              "sticky top-0 z-10 border-b border-subtle bg-surface-1 py-2 text-caption-sm-medium text-tertiary"
            )}
          >
            <span />
            <span>ID</span>
            <span>Milestone</span>
            <span>Status</span>
            <span>Progress</span>
            <span className="text-right">Modules</span>
            <span className="text-right">Deliverables</span>
            <span className="text-right">Amount</span>
            <span className="text-right">Payment</span>
            <span />
          </div>

          {isLoading && !milestones ? (
            <div className="px-page-x py-6 text-body-xs-regular text-tertiary">Loading milestones…</div>
          ) : milestones?.length === 0 ? (
            <div className="px-page-x py-10 text-center">
              <div className="text-body-sm-medium text-primary">No milestones yet</div>
              <p className="mt-1 text-body-xs-regular text-tertiary">
                Add milestones manually or import the SOW to create milestones, deliverables, modules, features and
                tasks.
              </p>
              {isAdmin && (
                <div className="mt-4 flex justify-center">
                  <Button
                    variant="secondary"
                    size="md"
                    stretch="auto"
                    icon={<AddOutline />}
                    label="Add milestone"
                    onClick={() => setMilestoneModal({ isOpen: true })}
                  />
                </div>
              )}
            </div>
          ) : (
            milestones?.map((milestone) => {
              const status = getMilestoneStatus(milestone);
              const progress = getMilestoneProgress(milestone);
              const isOpen = expanded.has(milestone.id);
              const deliverableCount = (deliverables ?? []).filter((d) => d.milestone_id === milestone.id).length;
              return (
                <Fragment key={milestone.id}>
                  <div
                    role="row"
                    tabIndex={0}
                    aria-expanded={isOpen}
                    className={cn(
                      MILESTONE_GRID,
                      "group cursor-pointer border-b border-subtle py-2 text-body-xs-regular hover:bg-layer-transparent-hover",
                      { "bg-layer-1": isOpen }
                    )}
                    onClick={() => toggle(milestone.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggle(milestone.id);
                      }
                    }}
                  >
                    <span className="grid place-items-center text-secondary">
                      {isOpen ? (
                        <ChevronDownOutline className="size-3.5" />
                      ) : (
                        <ChevronRightOutline className="size-3.5" />
                      )}
                    </span>
                    <span className="text-caption-md-medium text-secondary">{milestone.code || "—"}</span>
                    <span className="truncate pr-3 text-body-xs-medium text-primary" title={milestone.name}>
                      {milestone.name}
                    </span>
                    <span>
                      <Badge variant={STATUS_BADGE_VARIANT[status]} size="sm" label={MILESTONE_STATUS_LABEL[status]} />
                    </span>
                    <span className="flex items-center gap-2 pr-4">
                      <ProgressBar value={progress} isComplete={milestone.is_completed} className="flex-1" />
                      <span className="w-20 shrink-0 text-right text-caption-sm-regular whitespace-nowrap text-tertiary">
                        {milestone.completed_issues + milestone.cancelled_issues} / {milestone.total_issues}
                      </span>
                    </span>
                    <span className="text-right text-secondary">{milestone.modules.length}</span>
                    <span className="text-right text-secondary">{deliverableCount}</span>
                    <span className="text-right text-primary">{formatAmount(milestone.amount)}</span>
                    <span className="text-right text-primary">{formatPercentage(milestone.payment_percentage)}</span>
                    <span className="flex justify-end gap-0.5 pr-2">
                      {isAdmin && (
                        <>
                          <IconButton
                            variant="ghost"
                            size="sm"
                            icon={<EditOutline />}
                            aria-label={`Edit ${milestone.name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setMilestoneModal({ isOpen: true, data: milestone });
                            }}
                          />
                          <IconButton
                            variant="ghost"
                            size="sm"
                            icon={<DeleteOutline />}
                            aria-label={`Delete ${milestone.name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteTarget(milestone);
                            }}
                          />
                        </>
                      )}
                    </span>
                  </div>
                  {isOpen && renderDetails(milestone)}
                </Fragment>
              );
            })
          )}
        </div>
      </div>

      <MilestoneFormModal
        isOpen={milestoneModal.isOpen}
        data={milestoneModal.data}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        onClose={() => setMilestoneModal({ isOpen: false })}
      />
      <ConfirmDialog
        isOpen={!!deleteTarget}
        handleClose={() => setDeleteTarget(null)}
        handleSubmit={handleDelete}
        isSubmitting={isDeleting}
        title="Delete milestone"
        content={
          <>
            Are you sure you want to delete{" "}
            <span className="font-medium break-all text-primary">{deleteTarget?.name}</span>? Its deliverables and work
            items are kept but will no longer belong to a milestone.
          </>
        }
      />
    </div>
  );
});
