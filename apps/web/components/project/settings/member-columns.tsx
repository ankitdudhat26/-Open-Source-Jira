/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// oxlint-disable no-constant-binary-expression -- upstream code
import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { Controller, useForm } from "react-hook-form";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { DeleteOutline, LogOutOutline } from "@makeplane/propel/icons";
// plane imports
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { ROLE, EUserPermissions } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { EUserProjectRoles, IWorkspaceMember, TProjectMembership } from "@plane/types";
import { getFileURL } from "@plane/utils";
// hooks
import { ProjectRoleInput } from "@/components/members/project-role-input";
import { useMember } from "@/hooks/store/use-member";
import { useUser } from "@/hooks/store/user";

export interface RowData extends Pick<TProjectMembership, "original_role" | "designation"> {
  member: IWorkspaceMember;
}

type NameProps = {
  rowData: RowData;
  workspaceSlug: string;
};

type RemoveProps = {
  rowData: RowData;
  /** Settings → Roles & access: Project members → Delete (a project admin by default) */
  canRemoveMembers: boolean;
  currentProjectRole: EUserPermissions | undefined;
  setRemoveMemberModal: (rowData: RowData) => void;
};

type TRoleOption = {
  key: string;
  label: string;
};

type AccountTypeProps = {
  rowData: RowData;
  currentProjectRole: EUserPermissions | undefined;
  workspaceSlug: string;
  projectId: string;
  /** Settings → Roles & access: Project members → Edit (a project admin by default) */
  canChangeMembers: boolean;
};

export function NameColumn(props: NameProps) {
  const { rowData, workspaceSlug } = props;
  // derived values
  const { avatar_url, display_name, email, first_name, id, last_name } = rowData.member;

  return (
    <div className="group relative">
      <div className="flex w-56 items-center gap-2">
        <div className="flex flex-1 items-center gap-x-2 gap-y-2">
          {avatar_url && avatar_url.trim() !== "" ? (
            <Link href={`/${workspaceSlug}/profile/${id}`}>
              <span className="relative flex size-6 items-center justify-center rounded-full text-on-color capitalize">
                <img
                  src={getFileURL(avatar_url)}
                  className="absolute top-0 left-0 h-full w-full rounded-full object-cover"
                  alt={display_name || email}
                />
              </span>
            </Link>
          ) : (
            <Link href={`/${workspaceSlug}/profile/${id}`}>
              <span className="relative flex size-6 items-center justify-center rounded-full bg-layer-3 text-11 text-on-color capitalize">
                {(email ?? display_name ?? "?")[0]}
              </span>
            </Link>
          )}
          {first_name} {last_name}
        </div>
      </div>
    </div>
  );
}

/**
 * Remove (or Leave, on your own row) at the end of the row. Shown only where it works: the API refuses removing
 * someone with a higher project role than yours, and only workspace admins remove a workspace admin.
 */
export const RemoveMemberColumn = observer(function RemoveMemberColumn(props: RemoveProps) {
  const { rowData, canRemoveMembers, currentProjectRole, setRemoveMemberModal } = props;
  const { t } = useTranslation();
  const {
    workspace: { getWorkspaceMemberDetails },
  } = useMember();
  const { data: currentUser } = useUser();
  const { id, first_name, last_name } = rowData.member;
  const isCurrentUser = id === currentUser?.id;
  const isCurrentUserWorkspaceAdmin =
    !!currentUser && Number(getWorkspaceMemberDetails(currentUser.id)?.role) === EUserPermissions.ADMIN;
  const isRowWorkspaceAdmin = Number(getWorkspaceMemberDetails(id)?.role) === EUserPermissions.ADMIN;
  const isHigherRole =
    (rowData.original_role ?? EUserPermissions.GUEST) > (currentProjectRole ?? EUserPermissions.GUEST);
  const canRemove = canRemoveMembers && !isHigherRole && (!isRowWorkspaceAdmin || isCurrentUserWorkspaceAdmin);
  if (!isCurrentUser && !canRemove) return <div className="w-10" />;
  const label = isCurrentUser ? t("leave") : t("remove");

  return (
    <div className="flex w-10 justify-end">
      <Tooltip label={label}>
        <IconButton
          variant="ghost"
          size="sm"
          icon={<Icon icon={isCurrentUser ? LogOutOutline : DeleteOutline} />}
          aria-label={`${label} ${first_name ?? ""} ${last_name ?? ""}`.trim()}
          onClick={() => setRemoveMemberModal(rowData)}
        />
      </Tooltip>
    </div>
  );
});

export const AccountTypeColumn = observer(function AccountTypeColumn(props: AccountTypeProps) {
  const { rowData, projectId, workspaceSlug, canChangeMembers } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const {
    project: { updateMemberRole },
    workspace: { getWorkspaceMemberDetails },
  } = useMember();
  const { data: currentUser } = useUser();
  // form info
  const {
    control,
    formState: { errors },
  } = useForm();
  // derived values
  const roleLabel = ROLE[rowData.original_role ?? EUserPermissions.GUEST];
  const isCurrentUser = currentUser?.id === rowData.member.id;
  const isRowDataWorkspaceAdmin = [EUserPermissions.ADMIN].includes(
    Number(getWorkspaceMemberDetails(rowData.member.id)?.role) ?? EUserPermissions.GUEST
  );
  const isCurrentUserWorkspaceAdmin = currentUser
    ? [EUserPermissions.ADMIN].includes(
        Number(getWorkspaceMemberDetails(currentUser.id)?.role) ?? EUserPermissions.GUEST
      )
    : false;
  // logic
  // Workspace admin can change his own role
  // Whoever Settings → Roles & access lets change project members (a project admin by default) can change any role
  // except their own and a workspace admin's
  const isRoleEditable =
    (isCurrentUserWorkspaceAdmin && isCurrentUser) || (canChangeMembers && !isRowDataWorkspaceAdmin && !isCurrentUser);
  const checkCurrentOptionWorkspaceRole = (value: string) => {
    const currentMemberWorkspaceRole = getWorkspaceMemberDetails(value)?.role as EUserPermissions | undefined;
    if (!value || !currentMemberWorkspaceRole) return ROLE;

    const isGuest = [EUserPermissions.GUEST].includes(currentMemberWorkspaceRole);

    return Object.fromEntries(
      Object.entries(ROLE).filter(([key]) => !isGuest || parseInt(key) === EUserPermissions.GUEST)
    );
  };

  return (
    <>
      {isRoleEditable ? (
        <Controller
          name="role"
          control={control}
          rules={{ required: "Role is required." }}
          render={() => {
            const roleOptions: TRoleOption[] = Object.entries(checkCurrentOptionWorkspaceRole(rowData.member.id)).map(
              ([key, label]) => ({ key, label })
            );
            return (
              <div className="w-32">
                <Select<TRoleOption>
                  getValues={() => roleOptions}
                  value={roleOptions.find((option) => option.key === String(rowData.original_role)) ?? null}
                  onChange={(value) => {
                    if (!workspaceSlug || !value) return;
                    void updateMemberRole(
                      workspaceSlug.toString(),
                      projectId.toString(),
                      rowData.member.id,
                      Number(value) as EUserProjectRoles
                    ).catch((err) => {
                      console.log(err, "err");
                      const error = err.error;
                      const errorString = Array.isArray(error) ? error[0] : error;

                      setToast({
                        type: "error",
                        title: "You can’t change this role yet.",
                        message: errorString ?? "An error occurred while updating member role. Please try again.",
                      });
                    });
                  }}
                  getOptionValue={(option) => option.key}
                  getOptionLabel={(option) => option.label}
                  placeholder={t("role")}
                  showSearch={false}
                  pinSelected={false}
                >
                  <Select.Trigger<TRoleOption>
                    variant="select-ghost-md"
                    className={errors.role ? "border border-danger-strong" : undefined}
                  >
                    <span className="min-w-0 grow truncate text-left">{roleLabel}</span>
                  </Select.Trigger>
                </Select>
              </div>
            );
          }}
        />
      ) : (
        <div className="flex w-32">
          <span>{roleLabel}</span>
        </div>
      )}
    </>
  );
});

type ProjectRoleProps = {
  rowData: RowData;
  workspaceSlug: string;
  projectId: string;
  /** project admins can change it */
  isEditable: boolean;
};

/** The member's job on the project ("Developer", "Graphic Designer", ...), editable by project admins. */
export const ProjectRoleColumn = observer(function ProjectRoleColumn(props: ProjectRoleProps) {
  const { rowData, workspaceSlug, projectId, isEditable } = props;
  const {
    project: { updateMemberDesignation },
  } = useMember();
  const saved = rowData.designation ?? "";
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);

  if (!isEditable) return <div className="w-44 truncate">{saved || "—"}</div>;

  const save = () => {
    const value = draft.trim();
    if (value === saved) return;
    if (!value) {
      setDraft(saved);
      setToast({ type: "error", title: "Project role is required", message: "Enter the member's job on the project." });
      return;
    }
    void updateMemberDesignation(workspaceSlug, projectId, rowData.member.id, value)
      .then(() => setToast({ type: "success", title: "Project role updated", message: value }))
      .catch((error: { error?: string } | undefined) => {
        setDraft(saved);
        setToast({ type: "error", title: "Error!", message: error?.error ?? "Project role could not be updated." });
      });
  };

  return (
    <div className="w-44">
      <ProjectRoleInput
        value={draft}
        onChange={setDraft}
        onBlur={save}
        invalid={!draft.trim()}
        placeholder="Add project role"
        ariaLabel={`Project role of ${rowData.member.display_name}`}
      />
    </div>
  );
});
