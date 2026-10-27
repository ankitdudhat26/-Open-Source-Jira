/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { Controller, useForm } from "react-hook-form";
// plane imports
import { ROLE, EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { DeactivatedUserOutline, DeleteOutline, EditOutline, MoreHorizontalOutline } from "@makeplane/propel/icons";
import { Badge } from "@makeplane/propel/components/badge";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { IUser, IWorkspaceMember } from "@plane/types";
// plane ui
import { Select } from "@plane/blocks/select";
// helpers
import { getFileURL, renderFormattedDate } from "@plane/utils";
// hooks
import { ProjectRoleInput } from "@/components/members/project-role-input";
import { useMember } from "@/hooks/store/use-member";
import { useUser, useUserPermissions } from "@/hooks/store/user";
import { EditMemberDetailsModal } from "./edit-member-details-modal";

export interface RowData {
  member: IWorkspaceMember;
  role: EUserPermissions;
  is_active: boolean;
  /** job ("Developer", "Graphic Designer", ...), the default project role */
  company_role?: string | null;
}

type NameProps = {
  rowData: RowData;
  workspaceSlug: string;
  isAdmin: boolean;
  currentUser: IUser | undefined;
  setRemoveMemberModal: (rowData: RowData) => void;
};

type TRoleOption = { key: EUserPermissions; label: string };

const ROLE_OPTIONS: TRoleOption[] = Object.entries(ROLE).map(([key, label]) => ({
  key: Number(key) as EUserPermissions,
  label,
}));

type AccountTypeProps = {
  rowData: RowData;
  workspaceSlug: string;
};

export function NameColumn(props: NameProps) {
  const { rowData, workspaceSlug, isAdmin, currentUser, setRemoveMemberModal } = props;
  // plane hooks
  const { t } = useTranslation();
  // derived values
  const { avatar_url, display_name, email, first_name, id, last_name } = rowData.member;
  const isSuspended = rowData.is_active === false;
  const canEdit = isAdmin && id !== currentUser?.id;
  const [isEditOpen, setIsEditOpen] = useState(false);
  // a picture that fails (or an outside link that is gone) falls back to the initial, never a broken image
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => setImageFailed(false), [avatar_url]);

  return (
    <div className="group relative">
      <div className="flex w-72 items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-1 items-center gap-x-2 gap-y-2">
          {isSuspended ? (
            <div className="rounded-full bg-layer-1">
              <DeactivatedUserOutline className="size-6 text-placeholder" />
            </div>
          ) : avatar_url && avatar_url.trim() !== "" && !imageFailed ? (
            <Link href={`/${workspaceSlug}/profile/${id}`}>
              <span className="relative flex size-6 items-center justify-center rounded-full text-on-color capitalize">
                {/* the initial shows while the picture loads */}
                <span className="absolute inset-0 flex items-center justify-center rounded-full bg-layer-3 text-11 text-tertiary">
                  {(email ?? display_name ?? "?")[0]}
                </span>
                <img
                  src={getFileURL(avatar_url)}
                  className="absolute top-0 left-0 h-full w-full rounded-full object-cover"
                  alt={display_name || email}
                  loading="lazy"
                  decoding="async"
                  onError={() => setImageFailed(true)}
                />
              </span>
            </Link>
          ) : (
            <Link href={`/${workspaceSlug}/profile/${id}`}>
              <span className="relative flex size-6 items-center justify-center rounded-full bg-layer-3 text-11 text-tertiary capitalize">
                {(email ?? display_name ?? "?")[0]}
              </span>
            </Link>
          )}
          <span className={isSuspended ? "text-placeholder" : ""}>
            {first_name} {last_name}
          </span>
        </div>

        {!isSuspended && (isAdmin || id === currentUser?.id) && (
          <div className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 has-[[data-popup-open]]:opacity-100">
            <Menu>
              <MenuTrigger
                render={
                  <IconButton
                    variant="ghost"
                    size="sm"
                    aria-label={t("aria_labels.common.more_actions")}
                    icon={<Icon icon={MoreHorizontalOutline} />}
                  />
                }
              />
              <MenuContent side="bottom" align="end">
                {canEdit && (
                  <MenuItem
                    icon={<Icon icon={EditOutline} />}
                    label="Edit details"
                    onClick={() => setIsEditOpen(true)}
                  />
                )}
                <MenuItem
                  icon={<Icon icon={DeleteOutline} />}
                  label={id === currentUser?.id ? t("leave") : t("remove")}
                  onClick={() => setRemoveMemberModal(rowData)}
                />
              </MenuContent>
            </Menu>
          </div>
        )}
      </div>
      {canEdit && (
        <EditMemberDetailsModal
          rowData={rowData}
          workspaceSlug={workspaceSlug}
          isOpen={isEditOpen}
          onClose={() => setIsEditOpen(false)}
        />
      )}
    </div>
  );
}

export const AccountTypeColumn = observer(function AccountTypeColumn(props: AccountTypeProps) {
  const { rowData, workspaceSlug } = props;
  // form info
  const { control } = useForm();
  // store hooks
  const { allowPermissions } = useUserPermissions();

  const {
    workspace: { updateMember },
  } = useMember();
  const { data: currentUser } = useUser();

  // derived values
  const isCurrentUser = currentUser?.id === rowData.member.id;
  const isAdminRole = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const isRoleNonEditable = isCurrentUser || !isAdminRole;
  const isSuspended = rowData.is_active === false;

  return (
    <>
      {isSuspended ? (
        <div className="flex w-32">
          <Badge variant="neutral" size="sm" label="Suspended" />
        </div>
      ) : isRoleNonEditable ? (
        <div className="flex w-32">
          <span>{ROLE[rowData.role]}</span>
        </div>
      ) : (
        <Controller
          name="role"
          control={control}
          rules={{ required: "Role is required." }}
          render={() => (
            <div className="w-32">
              <Select<TRoleOption>
                value={ROLE_OPTIONS.find((role) => role.key === rowData.role) ?? null}
                onChange={(val) => {
                  if (!workspaceSlug) return;
                  updateMember(workspaceSlug.toString(), rowData.member.id, {
                    role: Number(val) as EUserPermissions,
                  }).catch((err: unknown) => {
                    const error = err as { error?: string | string[] };
                    const errorString = Array.isArray(error?.error) ? error.error[0] : error?.error;

                    setToast({
                      type: "error",
                      title: "Error!",
                      message: errorString ?? "An error occurred while updating member role. Please try again.",
                    });
                  });
                }}
                getValues={() => ROLE_OPTIONS}
                getOptionValue={(role) => String(role.key)}
                getOptionLabel={(role) => role.label}
                showSearch={false}
                pinSelected={false}
              >
                <Select.Trigger<TRoleOption> variant="select-ghost-md">
                  <span className="min-w-0 flex-1 truncate text-left">{ROLE[rowData.role]}</span>
                </Select.Trigger>
              </Select>
            </div>
          )}
        />
      )}
    </>
  );
});

type WorkspaceRoleProps = { rowData: RowData; workspaceSlug: string; isEditable: boolean };

/** The member's job ("Developer", "Graphic Designer", ...). It pre-fills the project role when they join a project. */
export const WorkspaceRoleColumn = observer(function WorkspaceRoleColumn(props: WorkspaceRoleProps) {
  const { rowData, workspaceSlug, isEditable } = props;
  const {
    workspace: { updateMember },
  } = useMember();
  const saved = rowData.company_role ?? "";
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);

  if (!isEditable) return <div className="w-44 truncate">{saved || "—"}</div>;

  const save = () => {
    const value = draft.trim();
    if (value === saved) return;
    void updateMember(workspaceSlug, rowData.member.id, { company_role: value })
      .then(() => setToast({ type: "success", title: "Role updated", message: value || "Role cleared" }))
      .catch((error: { error?: string } | undefined) => {
        setDraft(saved);
        setToast({ type: "error", title: "Error!", message: error?.error ?? "Role could not be updated." });
      });
  };

  return (
    <div className="w-44">
      <ProjectRoleInput
        value={draft}
        onChange={setDraft}
        onBlur={save}
        placeholder="Add role"
        ariaLabel={`Role of ${rowData.member.display_name}`}
      />
    </div>
  );
});

type AccessProps = { rowData: RowData; workspaceSlug: string; isAdmin: boolean };

const ACCESS_BADGE = {
  active: { variant: "success", label: "Active" },
  pending: { variant: "warning", label: "Not signed in yet" },
  no_access: { variant: "neutral", label: "No sign in" },
} as const;

/**
 * Whether the member can sign in, and for admins the invite: an email with the link to set a password, after which
 * the member signs in with that email. Members without an email (people from Jira) get one entered here.
 */
export const AccessColumn = observer(function AccessColumn(props: AccessProps) {
  const { rowData, workspaceSlug, isAdmin } = props;
  const {
    workspace: { sendMemberInvite, getWorkspaceMemberDetails },
  } = useMember();
  const { data: currentUser } = useUser();
  // states
  const [isOpen, setIsOpen] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [email, setEmail] = useState("");
  // derived values
  const { member } = rowData;
  const status = member.id === currentUser?.id ? "active" : (member.access_status ?? "active");
  const inviteSentAt = getWorkspaceMemberDetails(member.id)?.invite_sent_at;
  const canInvite = isAdmin && status !== "active" && rowData.is_active !== false;
  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());

  const open = () => {
    setEmail(member.email ?? "");
    setIsOpen(true);
  };

  const send = async () => {
    if (!isEmailValid) {
      setToast({ type: "error", title: "Email needed", message: "Enter a valid email address." });
      return;
    }
    setIsSending(true);
    try {
      const changed = email.trim().toLowerCase() !== (member.email ?? "").toLowerCase();
      await sendMemberInvite(workspaceSlug, member.id, changed ? email.trim() : undefined);
      setToast({
        type: "success",
        title: "Invite sent",
        message: `${member.display_name} will get an email at ${email.trim()} to set a password and sign in.`,
      });
      setIsOpen(false);
    } catch (error) {
      const message =
        error && typeof error === "object" && "error" in error && typeof error.error === "string"
          ? error.error
          : "The invite could not be sent. Please try again.";
      setToast({ type: "error", title: "Invite not sent", message });
    } finally {
      setIsSending(false);
    }
  };

  if (rowData.is_active === false) return null;

  return (
    <div className="flex w-max items-center gap-2 whitespace-nowrap">
      <Badge variant={ACCESS_BADGE[status].variant} size="sm" label={ACCESS_BADGE[status].label} />
      {canInvite && (
        <button
          type="button"
          className="rounded-md border border-subtle px-2 py-0.5 text-caption-md-medium text-accent-primary hover:bg-layer-transparent-hover"
          onClick={open}
        >
          {inviteSentAt ? "Resend invite" : "Invite"}
        </button>
      )}
      {canInvite && inviteSentAt && (
        <span className="text-caption-sm-regular text-tertiary">Sent {renderFormattedDate(inviteSentAt)}</span>
      )}
      <ConfirmDialog
        isOpen={isOpen}
        handleClose={() => !isSending && setIsOpen(false)}
        handleSubmit={send}
        isSubmitting={isSending}
        variant="primary"
        title={`Invite ${member.display_name}`}
        content={
          <div className="flex flex-col gap-3">
            <p>
              {member.display_name} gets an email with a link to set a password. Then they sign in with this email and
              that password, and see their work items, comments and history. The link works once, for 7 days.
            </p>
            <label className="flex flex-col gap-1">
              <span className="text-caption-md-medium text-secondary">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void send();
                }}
                placeholder="name@company.com"
                aria-label={`Email of ${member.display_name}`}
                className="rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary outline-none focus:border-accent-strong"
              />
            </label>
            {member.email && email.trim().toLowerCase() !== member.email.toLowerCase() && (
              <p className="text-caption-md-regular text-warning-primary">
                Their sign in email changes from {member.email} to {email.trim() || "—"}.
              </p>
            )}
          </div>
        }
        primaryButtonText={{ loading: "Sending…", default: "Send invite" }}
        secondaryButtonText="Cancel"
      />
    </div>
  );
});
