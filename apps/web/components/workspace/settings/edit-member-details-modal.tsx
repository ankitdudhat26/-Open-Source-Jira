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
import { renderFormattedDate } from "@plane/utils";
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

/** The account an email belongs to, which can be linked to the member (it signed up with the app link). */
type TMergeConflict = {
  data: TWorkspaceMemberDetailsForm;
  account: { display_name?: string; date_joined?: string; last_login?: string | null };
};

const errorMessage = (error: unknown, fallback: string) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string" ? error.error : fallback;

/**
 * Edit a member's details: name and job role always; the email only while the account was never signed in to (e.g.
 * people the Jira import added): for people who sign in it is their sign in, which they change themselves.
 */
export const EditMemberDetailsModal = observer(function EditMemberDetailsModal(props: Props) {
  const { rowData, workspaceSlug, isOpen, onClose } = props;
  const {
    workspace: { updateMemberDetails },
  } = useMember();
  const { member } = rowData;
  const canEditEmail = member.access_status !== "active";
  // states
  const [form, setForm] = useState<Required<Omit<TWorkspaceMemberDetailsForm, "merge_account">>>({
    first_name: "",
    last_name: "",
    display_name: "",
    email: "",
    company_role: "",
  });
  const [isSaving, setIsSaving] = useState(false);
  const [mergeConflict, setMergeConflict] = useState<TMergeConflict | null>(null);

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

  const field = (key: keyof typeof form, label: string, placeholder: string, disabled = false) => (
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
    if (!form.display_name.trim()) {
      setToast({ type: "error", title: "Display name needed", message: "Enter a display name." });
      return;
    }
    if (canEditEmail && form.email.trim() && !EMAIL_PATTERN.test(form.email.trim())) {
      setToast({ type: "error", title: "Check the email", message: "Enter a valid email address." });
      return;
    }
    const data: TWorkspaceMemberDetailsForm = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      display_name: form.display_name.trim(),
      company_role: form.company_role.trim(),
    };
    if (canEditEmail) {
      // a member without an email keeps none until one is typed
      if (form.email.trim() || member.email) data.email = form.email.trim();
    }
    await submit(data);
  };

  const submit = async (data: TWorkspaceMemberDetailsForm) => {
    setIsSaving(true);
    try {
      await updateMemberDetails(workspaceSlug, member.id, data);
      setToast({
        type: "success",
        title: data.merge_account ? "Accounts linked" : "Member updated",
        message: data.merge_account
          ? `${data.display_name ?? member.display_name} now signs in with ${data.email}.`
          : `${data.display_name ?? member.display_name} saved.`,
      });
      setMergeConflict(null);
      onClose();
    } catch (error) {
      // the email is the account the person made by signing up with the app link: ask to link it
      if (!data.merge_account && error && typeof error === "object" && "can_merge" in error && error.can_merge) {
        const account = "account" in error ? (error.account as TMergeConflict["account"]) : {};
        setMergeConflict({ data, account });
        return;
      }
      setToast({
        type: "error",
        title: "Not saved",
        message: errorMessage(error, "The member could not be updated. Please try again."),
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (mergeConflict)
    return (
      <ConfirmDialog
        isOpen={isOpen}
        handleClose={() => !isSaving && setMergeConflict(null)}
        handleSubmit={() => submit({ ...mergeConflict.data, merge_account: true })}
        isSubmitting={isSaving}
        variant="primary"
        title="Link the account?"
        content={
          <div className="flex flex-col gap-3">
            <p>
              {mergeConflict.data.email} already has an account
              {mergeConflict.account.date_joined
                ? `, made by signing up on ${renderFormattedDate(mergeConflict.account.date_joined)}`
                : ""}
              .
            </p>
            <p>
              Linking it makes it {member.display_name}: they sign in with that email and their own password and see all
              of {member.display_name}&apos;s work items, comments and history. The other account is switched off and
              its workspaces and projects move to {member.display_name}. They are signed out once and sign in again.
            </p>
          </div>
        }
        primaryButtonText={{ loading: "Linking…", default: "Link account" }}
        secondaryButtonText="Back"
      />
    );

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
            {field("first_name", "First name", "First name")}
            {field("last_name", "Last name", "Last name")}
          </div>
          {field("display_name", "Display name", "Name shown on work items")}
          {field("email", "Email", "name@company.com", !canEditEmail)}
          {field("company_role", "Role", "e.g. Developer, Graphic Designer")}
          <p className="text-caption-md-regular text-tertiary">
            {canEditEmail
              ? "This person has not signed in yet. A new email is the one they sign in with; send the invite again after changing it."
              : "This person signs in with this email, so only they can change it (in their profile settings)."}
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
