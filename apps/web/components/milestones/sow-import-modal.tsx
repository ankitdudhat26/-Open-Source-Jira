/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useDropzone } from "react-dropzone";
import { mutate } from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Dialog, DialogContent } from "@makeplane/propel/components/dialog";
import { FileSpreadsheetOutline, UploadOutline, WarningTriangleOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
import type { TSOWImportError, TSOWImportResponse } from "@plane/types";
// hooks
import { useLabel } from "@/hooks/store/use-label";
import { useModule } from "@/hooks/store/use-module";
import { useProject } from "@/hooks/store/use-project";
import {
  PROJECT_DELIVERABLES,
  PROJECT_MILESTONES,
  PROJECT_RESOURCES,
  PROJECT_WORK_ITEM_TYPES,
  projectMilestoneService,
  useProjectResources,
} from "@/hooks/use-project-milestones";
// local imports
import { formatAmount, formatPercentage } from "./helper";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
};

const ACCEPTED_FILES = {
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel.sheet.macroEnabled.12": [".xlsm"],
  "application/pdf": [".pdf"],
};

const COUNT_LABELS: { key: keyof TSOWImportResponse["summary"]["counts"]; label: string }[] = [
  { key: "milestones", label: "Milestones" },
  { key: "deliverables", label: "Deliverables" },
  { key: "modules", label: "Modules" },
  { key: "features", label: "Features" },
  { key: "tasks", label: "Tasks" },
  { key: "resources", label: "Resources" },
];

function MessageList(props: { title: string; messages: string[]; tone: "danger" | "warning" }) {
  const { title, messages, tone } = props;
  if (messages.length === 0) return null;
  return (
    <div
      className={`rounded-md border p-3 ${tone === "danger" ? "border-danger-subtle bg-danger-subtle" : "border-warning-subtle bg-warning-subtle"}`}
    >
      <div className="mb-1 flex items-center gap-1.5 text-body-xs-medium text-primary">
        <WarningTriangleOutline className="size-3.5 shrink-0" />
        {title} ({messages.length})
      </div>
      <ul className="vertical-scrollbar scrollbar-sm max-h-32 list-disc space-y-0.5 overflow-y-auto pl-5 text-caption-sm-regular text-secondary">
        {messages.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    </div>
  );
}

/** Upload a SOW, review what it contains, then import it into the project. */
export const SOWImportModal = observer(function SOWImportModal(props: Props) {
  const { isOpen, onClose, workspaceSlug, projectId } = props;
  // states
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<TSOWImportResponse | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // SOW resource ID -> member who fills the role; their tasks are assigned to them on import
  const [resourceMembers, setResourceMembers] = useState<Record<string, string>>({});
  // store hooks
  const { fetchModules } = useModule();
  const { fetchProjectLabels } = useLabel();
  const { fetchProjectDetails } = useProject();
  const { resources: existingResources } = useProjectResources(workspaceSlug, projectId);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setErrors([]);
    setWarnings([]);
    setIsLoading(false);
    setResourceMembers({});
  };

  const handleClose = () => {
    if (isLoading) return;
    reset();
    onClose();
  };

  const handleError = (error: unknown) => {
    const data = error as TSOWImportError | undefined;
    setPreview(null);
    setErrors(data?.errors?.length ? data.errors : [data?.error ?? "The SOW could not be read."]);
    setWarnings(data?.warnings ?? []);
  };

  const reviewFile = async (selected: File) => {
    setFile(selected);
    setErrors([]);
    setWarnings([]);
    setIsLoading(true);
    try {
      const response = await projectMilestoneService.importSOW(workspaceSlug, projectId, selected, true);
      setPreview(response);
      setWarnings(response.warnings);
      // keep the members already mapped to these resources by an earlier import
      setResourceMembers(
        Object.fromEntries(
          (existingResources ?? [])
            .filter((resource) => resource.code && resource.member_id)
            .map((resource) => [resource.code, resource.member_id as string])
        )
      );
    } catch (error) {
      handleError(error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleImport = async () => {
    if (!file) return;
    setIsLoading(true);
    try {
      const response = await projectMilestoneService.importSOW(workspaceSlug, projectId, file, false, resourceMembers);
      await Promise.all([
        mutate(PROJECT_MILESTONES(projectId)),
        mutate(PROJECT_DELIVERABLES(projectId)),
        mutate(PROJECT_RESOURCES(projectId)),
        mutate(PROJECT_WORK_ITEM_TYPES(projectId)),
        fetchModules(workspaceSlug, projectId),
        fetchProjectLabels(workspaceSlug, projectId),
        // the import turns on modules for the project
        fetchProjectDetails(workspaceSlug, projectId),
      ]);
      const { counts } = response.summary;
      setToast({
        type: "success",
        title: "SOW imported",
        message: `${counts.milestones} milestones, ${counts.modules} modules, ${counts.features} features and ${counts.tasks} tasks are in the project.`,
      });
      setIsLoading(false);
      handleClose();
    } catch (error) {
      setIsLoading(false);
      handleError(error);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: ACCEPTED_FILES,
    multiple: false,
    maxSize: 10 * 1024 * 1024,
    disabled: isLoading,
    onDropAccepted: (files) => {
      if (files[0]) void reviewFile(files[0]);
    },
    onDropRejected: () => setErrors(["Upload the SOW as an .xlsx or .pdf file smaller than 10 MB."]),
  });

  const summary = preview?.summary;

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
      disablePointerDismissal
    >
      <DialogContent size="lg" aria-label="Import SOW">
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="space-y-1 px-5 pt-5">
            <h3 className="text-18 font-medium text-secondary">Import SOW</h3>
            <p className="text-body-xs-regular text-tertiary">
              Upload the project plan (.xlsx or .pdf) with its Milestones, Deliverables, Resources, Modules, Features
              and Tasks. Milestones are linked to the modules delivered in them, features become Feature work items and
              tasks become Task work items under their feature. Importing the same SOW again updates the existing items.
            </p>
          </div>
          <div className="vertical-scrollbar scrollbar-sm min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
            <div
              {...getRootProps()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-6 text-center ${
                isDragActive ? "border-accent-strong bg-accent-subtle" : "border-subtle hover:bg-layer-1"
              }`}
            >
              <input {...getInputProps()} aria-label="SOW file" />
              {file ? (
                <>
                  <FileSpreadsheetOutline className="size-6 text-secondary" />
                  <span className="text-body-sm-medium text-primary">{file.name}</span>
                  <span className="text-caption-sm-regular text-tertiary">
                    {isLoading ? "Reading the SOW…" : "Drop another file or click to replace"}
                  </span>
                </>
              ) : (
                <>
                  <UploadOutline className="size-6 text-secondary" />
                  <span className="text-body-sm-medium text-primary">Drop the SOW here or click to browse</span>
                  <span className="text-caption-sm-regular text-tertiary">.xlsx or .pdf, up to 10 MB</span>
                </>
              )}
            </div>

            <MessageList title="Fix these in the SOW and upload it again" messages={errors} tone="danger" />
            <MessageList title="Warnings" messages={warnings} tone="warning" />

            {summary && (
              <>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {COUNT_LABELS.map(({ key, label }) => (
                    <div key={key} className="rounded-md border border-subtle px-3 py-2">
                      <div className="text-18 font-medium text-primary">{summary.counts[key]}</div>
                      <div className="text-caption-sm-regular text-tertiary">{label}</div>
                    </div>
                  ))}
                </div>
                <div className="overflow-x-auto rounded-md border border-subtle">
                  <table className="w-full text-left text-caption-md-regular">
                    <thead className="bg-layer-1 text-caption-sm-medium text-tertiary">
                      <tr>
                        <th className="px-3 py-2">ID</th>
                        <th className="px-3 py-2">Milestone</th>
                        <th className="px-3 py-2 text-right">Payment</th>
                        <th className="px-3 py-2">Modules</th>
                        <th className="px-3 py-2 text-right">Deliverables</th>
                        <th className="px-3 py-2 text-right">Features</th>
                        <th className="px-3 py-2 text-right">Tasks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.milestones.map((milestone) => (
                        <tr key={milestone.id} className="border-t border-subtle align-top">
                          <td className="px-3 py-2 text-tertiary">{milestone.id}</td>
                          <td className="px-3 py-2 text-primary">
                            {milestone.name}
                            {milestone.amount && (
                              <div className="text-caption-sm-regular text-tertiary">
                                {formatAmount(milestone.amount)}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right">{formatPercentage(milestone.payment_percentage)}</td>
                          <td className="px-3 py-2 text-secondary">
                            {milestone.modules.map((module) => module.name).join(", ") || "—"}
                          </td>
                          <td className="px-3 py-2 text-right">{milestone.deliverables.length}</td>
                          <td className="px-3 py-2 text-right">{milestone.feature_count}</td>
                          <td className="px-3 py-2 text-right">{milestone.task_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div>
                  <h4 className="mb-1 text-body-xs-medium text-primary">Resources</h4>
                  <p className="mb-2 text-caption-sm-regular text-tertiary">
                    Map each resource to a project member. Every task of that resource is assigned to them.
                  </p>
                  <div className="overflow-x-auto rounded-md border border-subtle">
                    <table className="w-full text-left text-caption-md-regular">
                      <thead className="bg-layer-1 text-caption-sm-medium text-tertiary">
                        <tr>
                          <th className="px-3 py-2">ID</th>
                          <th className="px-3 py-2">Role</th>
                          <th className="px-3 py-2">Type</th>
                          <th className="px-3 py-2 text-right">Tasks</th>
                          <th className="px-3 py-2">Member</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.resources.map((resource) => (
                          <tr key={resource.id} className="border-t border-subtle align-middle">
                            <td className="px-3 py-1.5 text-tertiary">{resource.id}</td>
                            <td className="px-3 py-1.5 text-primary">
                              {resource.role}
                              <div className="text-caption-sm-regular text-tertiary">{resource.responsibilities}</div>
                            </td>
                            <td className="px-3 py-1.5 text-secondary">{resource.resource_type}</td>
                            <td className="px-3 py-1.5 text-right">{resource.task_count}</td>
                            <td className="w-48 px-3 py-1.5">
                              <MemberSelect
                                projectId={projectId}
                                value={resourceMembers[resource.id] ?? null}
                                onChange={(memberId) =>
                                  setResourceMembers((current) => {
                                    const next = { ...current };
                                    if (!memberId || memberId === current[resource.id]) delete next[resource.id];
                                    else next[resource.id] = memberId;
                                    return next;
                                  })
                                }
                                multiple={false}
                                variant="select-ghost-md"
                                placeholder="Map member"
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h4 className="mb-2 text-body-xs-medium text-primary">Modules</h4>
                    <ul className="divide-y divide-subtle rounded-md border border-subtle">
                      {summary.modules.map((module) => (
                        <li key={module.id} className="px-3 py-1.5">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="text-caption-md-regular text-primary">
                              <span className="mr-1.5 text-tertiary">{module.id}</span>
                              {module.name}
                            </span>
                            <span className="shrink-0 text-caption-sm-regular text-tertiary">
                              {module.feature_count} features · {module.task_count} tasks
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="mb-2 text-body-xs-medium text-primary">Deliverables</h4>
                    <ul className="divide-y divide-subtle rounded-md border border-subtle">
                      {summary.deliverables.map((deliverable) => (
                        <li key={deliverable.id} className="flex items-baseline justify-between gap-2 px-3 py-1.5">
                          <span className="text-caption-md-regular text-primary">
                            <span className="mr-1.5 text-tertiary">{deliverable.id}</span>
                            {deliverable.name}
                          </span>
                          <span className="shrink-0 text-caption-sm-regular text-tertiary">
                            {deliverable.milestone_id}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </>
            )}
          </div>
          <div className="flex items-center justify-end gap-2 border-t-[0.5px] border-subtle px-5 py-4">
            <Button
              variant="secondary"
              size="md"
              stretch="auto"
              label="Cancel"
              onClick={handleClose}
              disabled={isLoading}
            />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={isLoading && preview ? "Importing" : "Import"}
              loading={isLoading && !!preview}
              disabled={!preview || isLoading || errors.length > 0}
              onClick={handleImport}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
});
