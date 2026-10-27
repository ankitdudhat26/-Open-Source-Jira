/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { TWorkspaceMemberDetailsForm } from "@plane/types";
// hooks
import { useMember } from "@/hooks/store/use-member";
// local imports
import type { RowData } from "./member-columns";

type Props = {
  rowData: RowData;
  workspaceSlug: string;
  isOpen: boolean;
  onClose: () => void;
};

const INPUT =
  "w-full rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary outline-none focus:border-accent-strong disabled:cursor-not-allowed disabled:text-tertiary";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Edit a member's details. Name and email only while the account was never signed in to (e.g. people the Jira
 * import added); people who sign in change those themselves. The job role can always be set.
 */
export const EditMemberDetailsModal = observer(function EditMemberDetailsModal(props: Props) {
  const { rowData, workspaceSlug, isOpen, onClose } = props;
  const {
    workspace: { updateMemberDetails },
  } = useMember();
  const { member } = rowData;
  const canEditAccount = member.access_status !== "active";
  // states
  const [form, setForm] = useState<Required<TWorkspaceMemberDetailsForm>>({
    first_name: "",
    last_name: "",
    display_name: "",
    email: "",
    company_role: "",
  });
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setForm({
      first_name: member.first_name ?? "",
      last_name: member.last_name ?? "",
      display_name: member.display_name ?? "",
      email: member.email ?? "",
      company_role: rowData.company_role ?? "",
    });
  }, [isOpen, member, rowData.company_role]);

  const field = (key: keyof TWorkspaceMemberDetailsForm, label: string, placeholder: string, disabled = false) => (
    <label className="flex flex-col gap-1">
      <span className="text-caption-md-medium text-secondary">{label}</span>
      <input
        type={key === "email" ? "email" : "text"}
        value={form[key]}
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        placeholder={placeholder}
        disabled={disabled || isSaving}
        maxLength={255}
        className={INPUT}
      />
    </label>
  );

  const save = async () => {
    if (canEditAccount && !form.display_name.trim()) {
      setToast({ type: "error", title: "Display name needed", message: "Enter a display name." });
      return;
    }
    if (canEditAccount && form.email.trim() && !EMAIL_PATTERN.test(form.email.trim())) {
      setToast({ type: "error", title: "Check the email", message: "Enter a valid email address." });
      return;
    }
    const data: TWorkspaceMemberDetailsForm = { company_role: form.company_role.trim() };
    if (canEditAccount) {
      data.first_name = form.first_name.trim();
      data.last_name = form.last_name.trim();
      data.display_name = form.display_name.trim();
      // a member without an email keeps none until one is typed
      if (form.email.trim() || member.email) data.email = form.email.trim();
    }
    setIsSaving(true);
    try {
      await updateMemberDetails(workspaceSlug, member.id, data);
      setToast({
        type: "success",
        title: "Member updated",
        message: `${data.display_name ?? member.display_name} saved.`,
      });
      onClose();
    } catch (error) {
      const message =
        error && typeof error === "object" && "error" in error && typeof error.error === "string"
          ? error.error
          : "The member could not be updated. Please try again.";
      setToast({ type: "error", title: "Not saved", message });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <ConfirmDialog
      isOpen={isOpen}
      handleClose={() => !isSaving && onClose()}
      handleSubmit={save}
      isSubmitting={isSaving}
      variant="primary"
      title={`Edit ${member.display_name}`}
      content={
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            {field("first_name", "First name", "First name", !canEditAccount)}
            {field("last_name", "Last name", "Last name", !canEditAccount)}
          </div>
          {field("display_name", "Display name", "Name shown on work items", !canEditAccount)}
          {field("email", "Email", "name@company.com", !canEditAccount)}
          {field("company_role", "Role", "e.g. Developer, Graphic Designer")}
          <p className="text-caption-md-regular text-tertiary">
            {canEditAccount
              ? "This person has not signed in yet. A new email is the one they sign in with; send the invite again after changing it."
              : "This person signs in with their own account, so only they can change their name and email (in their profile settings)."}
          </p>
          {/* Enter in any field saves */}
          <button type="submit" hidden aria-hidden tabIndex={-1} />
        </form>
      }
      primaryButtonText={{ loading: "Saving…", default: "Save" }}
      secondaryButtonText="Cancel"
    />
  );
});
