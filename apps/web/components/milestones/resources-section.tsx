/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Controller, useForm } from "react-hook-form";
import { mutate } from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Dialog, DialogContent } from "@makeplane/propel/components/dialog";
import { Field } from "@makeplane/propel/components/field";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { Select, SelectContent, SelectItem, SelectList, SelectTrigger } from "@makeplane/propel/components/select";
import { TextArea, TextAreaGroup } from "@makeplane/propel/components/text-area";
import { AddOutline, DeleteOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TProjectResource } from "@plane/types";
import { cn } from "@plane/utils";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { PROJECT_RESOURCES, projectMilestoneService, useProjectResources } from "@/hooks/use-project-milestones";

type Props = {
  workspaceSlug: string;
  projectId: string;
  isAdmin: boolean;
};

type TResourceForm = {
  role: string;
  resource_type: string;
  responsibilities: string;
  member_id: string | null;
};

// ID | Role | Resource type | Responsibilities | Member | Tasks done | actions
const RESOURCE_GRID = "grid grid-cols-[64px_minmax(180px,1fr)_130px_minmax(240px,1.6fr)_210px_160px_48px] items-center";

const DEFAULT_RESOURCE: TResourceForm = { role: "", resource_type: "", responsibilities: "", member_id: null };

/** The roles a resource can fill, in the order the Role dropdown lists them. */
const RESOURCE_ROLES = [
  "3D Artist",
  "Admin",
  "AI",
  "Android",
  "Angular JS",
  "API Development",
  "BA",
  "Backend",
  "Blockchain",
  "Business Consultant",
  "CI Backend",
  "Content Writer",
  "Data Labelling",
  "Design",
  "devOps",
  "Discovery Phase",
  "Embedded",
  "EXTJS",
  "Flutter",
  "Ionic",
  "iOS",
  "JAVA",
  "Java + Angular JS",
  "Java + React JS",
  "KT",
  "Laravel Backend",
  "Maintenance Package",
  ".Net Backend",
  "Next js",
  "Node JS",
  "Node JS + Angular JS",
  "Node JS + React JS",
  "Other",
  "Partner Development Manager",
  "Project Management",
  "PyQt5",
  "Python",
  "Python + Angular JS",
  "Python + React JS",
  "React JS",
  "React Native",
  "Salesforce",
  "Selenium",
  "SEO",
  "Support",
  "System Admin",
  "System Admin + DevOps",
  "Testing",
  "Trainees",
  "Unity Game Development",
  "Video Editor",
  "Web Designer",
  "Website",
  "Wordpress Website",
];
const RESOURCE_ROLE_ITEMS = RESOURCE_ROLES.map((role) => ({ value: role, label: role }));

const ResourceFormModal = observer(function ResourceFormModal(props: {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
}) {
  const { isOpen, onClose, workspaceSlug, projectId } = props;
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<TResourceForm>({ defaultValues: DEFAULT_RESOURCE });
  const {
    project: { fetchProjectMembers },
  } = useMember();
  useEffect(() => {
    if (isOpen) reset(DEFAULT_RESOURCE);
  }, [isOpen, reset]);

  const onSubmit = async (formData: TResourceForm) => {
    try {
      await projectMilestoneService.createResource(workspaceSlug, projectId, {
        ...formData,
        role: formData.role.trim(),
      });
      await mutate(PROJECT_RESOURCES(projectId));
      // the mapped member joined the project and was emailed an invite
      if (formData.member_id) await fetchProjectMembers(workspaceSlug, projectId);
      setToast({
        type: "success",
        title: "Success!",
        message: formData.member_id ? "Resource added. The member now has access to the project." : "Resource added.",
      });
      onClose();
    } catch {
      setToast({ type: "error", title: "Error!", message: "Resource could not be added." });
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
      <DialogContent size="md" aria-label="Add resource">
        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-4 p-5">
            <h3 className="text-18 font-medium text-secondary">Add resource</h3>
            <div>
              <Controller
                control={control}
                name="role"
                rules={{ validate: (value) => value.trim() !== "" || "Role is required" }}
                render={({ field: { value, onChange } }) => (
                  <Field name="role" invalid={Boolean(errors.role)}>
                    <Select<string>
                      items={RESOURCE_ROLE_ITEMS}
                      value={value || null}
                      onValueChange={(role) => {
                        if (role) onChange(role);
                      }}
                    >
                      <SelectTrigger size="md" placeholder="Select role" aria-label="Role" />
                      <SelectContent side="bottom" align="start">
                        <SelectList>
                          {RESOURCE_ROLE_ITEMS.map((option) => (
                            <SelectItem key={option.value} value={option.value} size="md" label={option.label} />
                          ))}
                        </SelectList>
                      </SelectContent>
                    </Select>
                  </Field>
                )}
              />
              <span className="text-11 text-danger-primary">{errors.role?.message}</span>
            </div>
            <Controller
              control={control}
              name="resource_type"
              render={({ field: { value, onChange } }) => (
                <Field name="resource_type">
                  <InputGroup size="lg">
                    <Input
                      size="lg"
                      type="text"
                      value={value}
                      onChange={onChange}
                      placeholder="Resource type, e.g. QA"
                    />
                  </InputGroup>
                </Field>
              )}
            />
            <Controller
              control={control}
              name="responsibilities"
              render={({ field: { value, onChange } }) => (
                <Field name="responsibilities">
                  <TextAreaGroup resize="none">
                    <TextArea
                      size="lg"
                      surface="field"
                      autoResize
                      maxRows={6}
                      value={value}
                      onChange={onChange}
                      placeholder="Responsibilities"
                    />
                  </TextAreaGroup>
                </Field>
              )}
            />
            <div>
              <span className="mb-1 block text-caption-md-medium text-secondary">Member</span>
              <Controller
                control={control}
                name="member_id"
                render={({ field: { value, onChange } }) => (
                  <MemberSelect
                    projectId={projectId}
                    workspaceAssignable
                    value={value}
                    onChange={(memberId) => onChange(!memberId || memberId === value ? null : memberId)}
                    multiple={false}
                    variant="pill-md"
                    placeholder="Select member"
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
              label="Add resource"
            />
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
});

/**
 * SOW resources (roles) and the member filling each one. Any workspace member can be mapped: they join the project
 * and get an invite email, their resource's tasks are assigned to them, and they are who the Assignees pickers offer.
 */
export const ResourcesSection = observer(function ResourcesSection(props: Props) {
  const { workspaceSlug, projectId, isAdmin } = props;
  // states
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TProjectResource | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  // hooks
  const { resources } = useProjectResources(workspaceSlug, projectId);
  const {
    project: { fetchProjectMembers },
  } = useMember();

  const handleMemberChange = async (resource: TProjectResource, memberId: string | null) => {
    setUpdatingId(resource.id);
    try {
      await projectMilestoneService.updateResource(workspaceSlug, projectId, resource.id, { member_id: memberId });
      await mutate(PROJECT_RESOURCES(projectId));
      // the mapped member joined the project and was emailed an invite
      if (memberId) await fetchProjectMembers(workspaceSlug, projectId);
      setToast({
        type: "success",
        title: "Success!",
        message: memberId
          ? `${resource.task_count} work items of ${resource.role} are assigned to the selected member, who now has access to the project.`
          : `${resource.role} is no longer mapped to a member.`,
      });
    } catch {
      setToast({ type: "error", title: "Error!", message: "Member could not be mapped." });
    } finally {
      setUpdatingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await projectMilestoneService.deleteResource(workspaceSlug, projectId, deleteTarget.id);
      await mutate(PROJECT_RESOURCES(projectId));
      setDeleteTarget(null);
    } catch {
      setToast({ type: "error", title: "Error!", message: "Resource could not be deleted." });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-subtle px-page-x py-2.5">
        <span className="text-caption-sm-regular text-tertiary">
          Map each role to the member who fills it. They get access to the project and an invite email, their tasks are
          assigned to them automatically, and they are the people offered in Assignees.
        </span>
        {isAdmin && (
          <div className="ml-auto">
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              icon={<AddOutline />}
              label="Add resource"
              onClick={() => setIsAddOpen(true)}
            />
          </div>
        )}
      </div>
      <div className="vertical-scrollbar horizontal-scrollbar scrollbar-md min-h-0 flex-1 overflow-auto">
        <div role="table" aria-label="Resources" className="min-w-[1000px]">
          <div
            role="row"
            className={cn(
              RESOURCE_GRID,
              "sticky top-0 z-10 border-b border-subtle bg-surface-1 py-2 pl-page-x text-caption-sm-medium text-tertiary"
            )}
          >
            <span>ID</span>
            <span>Role</span>
            <span>Resource type</span>
            <span>Responsibilities</span>
            <span>Member</span>
            <span>Tasks done</span>
            <span />
          </div>
          {!resources || resources.length === 0 ? (
            <div className="px-page-x py-6 text-body-xs-regular text-tertiary">
              No resources yet. Add them with Add resource, or import a SOW on a Fixed Cost project.
            </div>
          ) : (
            resources.map((resource) => {
              const progress = resource.task_count ? Math.round((resource.done_count / resource.task_count) * 100) : 0;
              return (
                <div
                  key={resource.id}
                  role="row"
                  className={cn(
                    RESOURCE_GRID,
                    "border-b border-subtle py-1.5 pl-page-x text-body-xs-regular hover:bg-layer-transparent-hover"
                  )}
                >
                  <span className="text-caption-md-medium text-secondary">{resource.code || "—"}</span>
                  <span className="truncate pr-3 text-primary" title={resource.role}>
                    {resource.role}
                  </span>
                  <span className="truncate pr-3 text-secondary">{resource.resource_type || "—"}</span>
                  <span className="truncate pr-3 text-secondary" title={resource.responsibilities}>
                    {resource.responsibilities || "—"}
                  </span>
                  <span className="min-w-0 pr-3">
                    <MemberSelect
                      projectId={projectId}
                      workspaceAssignable
                      value={resource.member_id}
                      onChange={(memberId) =>
                        handleMemberChange(resource, !memberId || memberId === resource.member_id ? null : memberId)
                      }
                      multiple={false}
                      variant="select-ghost-md"
                      placeholder="Map member"
                      disabled={!isAdmin || updatingId === resource.id}
                    />
                  </span>
                  <span className="flex items-center gap-2 pr-3">
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-layer-3">
                      <span className="block h-full rounded-full bg-accent-primary" style={{ width: `${progress}%` }} />
                    </span>
                    <span className="w-14 shrink-0 text-right text-caption-sm-regular text-tertiary">
                      {resource.done_count} / {resource.task_count}
                    </span>
                  </span>
                  <span className="flex justify-end pr-2">
                    {isAdmin && (
                      <IconButton
                        variant="ghost"
                        size="sm"
                        icon={<DeleteOutline />}
                        aria-label={`Delete ${resource.role}`}
                        onClick={() => setDeleteTarget(resource)}
                      />
                    )}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
      <ResourceFormModal
        isOpen={isAddOpen}
        onClose={() => setIsAddOpen(false)}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
      />
      <ConfirmDialog
        isOpen={!!deleteTarget}
        handleClose={() => setDeleteTarget(null)}
        handleSubmit={handleDelete}
        isSubmitting={isDeleting}
        title="Delete resource"
        content={
          <>
            Delete <span className="font-medium text-primary">{deleteTarget?.role}</span>? Its label and the current
            assignees of its tasks are kept.
          </>
        }
      />
    </div>
  );
});
