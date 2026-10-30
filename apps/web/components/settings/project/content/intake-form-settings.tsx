/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { Switch } from "@makeplane/propel/components/switch";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { copyTextToClipboard, renderFormattedDate } from "@plane/utils";
// components
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";
// services
import type { TIntakeFormField, TIntakeFormInvite } from "@/services/intake-form.service";
import { intakeFormService } from "@/services/intake-form.service";

type Props = {
  workspaceSlug: string;
  projectId: string;
  /** Intake is on for the project — the form sends its requests there */
  isIntakeEnabled: boolean;
};

const FIELD_DESCRIPTIONS: Record<string, string> = {
  title: "A short summary of the request. Always on the form.",
  description: "The details of what is needed.",
  type: "Feature, Bug, Task… from this project's work item types.",
  priority: "How urgent the request is.",
  labels: "This project's labels.",
  attachments: "Documents, screenshots and other files.",
};

const errorMessage = (error: unknown, fallback: string) => (error as { error?: string } | undefined)?.error ?? fallback;

const splitEmails = (text: string) =>
  text
    .split(/[\s,;]+/)
    .map((email) => email.trim())
    .filter(Boolean);

/**
 * The request form of the project's Intake. Its link is shared only with the clients invited here: they log in there
 * with their email to send requests and follow them (pending, accepted, declined with the reason). They are not
 * members of the project. The fields the form shows are chosen per project — all of them until turned off.
 */
export function IntakeFormSettings(props: Props) {
  const { workspaceSlug, projectId, isIntakeEnabled } = props;
  const [emails, setEmails] = useState("");
  const [isInviting, setIsInviting] = useState(false);
  const [isResetOpen, setIsResetOpen] = useState(false);
  const [toRemove, setToRemove] = useState<TIntakeFormInvite | null>(null);

  const key = workspaceSlug && projectId ? [workspaceSlug, projectId] : null;
  const { data: form, mutate: mutateForm } = useSWR(
    key ? ["INTAKE_FORM", ...key] : null,
    () => intakeFormService.fetch(workspaceSlug, projectId),
    { revalidateOnFocus: false }
  );
  const { data: invites, mutate: mutateInvites } = useSWR(
    key ? ["INTAKE_FORM_INVITES", ...key] : null,
    () => intakeFormService.fetchInvites(workspaceSlug, projectId),
    { revalidateOnFocus: false }
  );

  if (!form) return null;

  const handleLinkToggle = async (isEnabled: boolean) => {
    try {
      await mutateForm(intakeFormService.update(workspaceSlug, projectId, { is_enabled: isEnabled }), {
        optimisticData: { ...form, is_enabled: isEnabled },
        rollbackOnError: true,
        revalidate: false,
      });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The link could not be updated.") });
    }
  };

  const handleFieldToggle = async (field: TIntakeFormField, visible: boolean) => {
    const optimistic = {
      ...form,
      fields: form.fields.map((item) => (item.key === field.key ? { ...item, visible } : item)),
    };
    try {
      await mutateForm(intakeFormService.update(workspaceSlug, projectId, { fields: { [field.key]: { visible } } }), {
        optimisticData: optimistic,
        rollbackOnError: true,
        revalidate: false,
      });
    } catch {
      setToast({ type: "error", title: "Error!", message: `${field.label} could not be updated. Try again.` });
    }
  };

  const sendInvites = async (list: string[], successMessage: string) => {
    setIsInviting(true);
    try {
      await mutateInvites(intakeFormService.invite(workspaceSlug, projectId, list), { revalidate: false });
      setToast({ type: "success", title: "Invitation sent", message: successMessage });
      return true;
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The invitation could not be sent.") });
      return false;
    } finally {
      setIsInviting(false);
    }
  };

  const handleInvite = async () => {
    const list = splitEmails(emails);
    if (!list.length) return;
    const sent = await sendInvites(
      list,
      list.length === 1 ? `${list[0]} was emailed the link.` : `${list.length} people were emailed the link.`
    );
    if (sent) setEmails("");
  };

  const isLinkOn = form.is_enabled && isIntakeEnabled;

  return (
    <div className="flex flex-col gap-6">
      {/* the link */}
      <div className="flex flex-col gap-3">
        <SettingsBoxedControlItem
          title="Request link"
          description={
            isIntakeEnabled
              ? "Clients you invite below open this link and log in to send requests and follow their status. They do not see anything else of the project."
              : "Turn on Intake above to take requests from clients."
          }
          control={
            <Switch
              size="sm"
              checked={form.is_enabled}
              disabled={!isIntakeEnabled}
              onCheckedChange={(checked) => void handleLinkToggle(checked)}
              aria-label="Request link"
            />
          }
        />
        {isLinkOn && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <InputGroup size="md">
                <Input
                  size="md"
                  value={form.url}
                  readOnly
                  aria-label="Request link"
                  onFocus={(e) => e.target.select()}
                />
              </InputGroup>
            </div>
            <Button
              variant="secondary"
              size="md"
              stretch="auto"
              label="Copy link"
              onClick={() =>
                void copyTextToClipboard(form.url).then(() =>
                  setToast({ type: "success", title: "Link copied", message: "Only invited clients can use it." })
                )
              }
            />
            <Button
              variant="secondary"
              size="md"
              stretch="auto"
              label="Open"
              onClick={() => window.open(form.url, "_blank", "noopener,noreferrer")}
            />
            <Button variant="ghost" size="md" stretch="auto" label="Reset link" onClick={() => setIsResetOpen(true)} />
          </div>
        )}
      </div>

      {/* invited clients */}
      {isIntakeEnabled && (
        <div className="flex flex-col gap-3">
          <div>
            <h4 className="text-body-sm-medium text-primary">Invited clients</h4>
            <p className="text-caption-md-regular text-tertiary">
              Each person is emailed the link and logs in there with this email. Only they can send requests.
              {!form.is_enabled && " Turn on the request link so they can use it."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <InputGroup size="md">
                <Input
                  size="md"
                  value={emails}
                  placeholder="client@company.com, another@company.com"
                  aria-label="Emails to invite"
                  onChange={(e) => setEmails(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void handleInvite();
                    }
                  }}
                />
              </InputGroup>
            </div>
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={isInviting ? "Inviting..." : "Invite"}
              disabled={isInviting || !splitEmails(emails).length}
              onClick={() => void handleInvite()}
            />
          </div>
          {invites && invites.length > 0 && (
            <div className="divide-y divide-subtle rounded-lg border border-subtle">
              {invites.map((invite) => (
                <div key={invite.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-body-xs-medium text-primary">{invite.email}</p>
                    <p className="text-caption-sm-regular text-tertiary">
                      {invite.has_account
                        ? `Has an account${invite.name ? ` · ${invite.name}` : ""}`
                        : "Not signed up yet"}
                      {` · ${invite.request_count} ${invite.request_count === 1 ? "request" : "requests"}`}
                      {invite.last_sent_at ? ` · invited ${renderFormattedDate(invite.last_sent_at)}` : ""}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label="Resend"
                    disabled={isInviting}
                    onClick={() => void sendInvites([invite.email], `${invite.email} was emailed the link again.`)}
                  />
                  <Button variant="ghost" size="sm" stretch="auto" label="Remove" onClick={() => setToRemove(invite)} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* the fields */}
      <div className="flex flex-col gap-3">
        <div>
          <h4 className="text-body-sm-medium text-primary">Request form</h4>
          <p className="text-caption-md-regular text-tertiary">
            The fields clients see on the request form. Turn off what this project does not need.
          </p>
        </div>
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {form.fields.map((field) => (
            <div key={field.key} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-body-xs-medium text-primary">{field.label}</p>
                <p className="text-caption-md-regular text-tertiary">{FIELD_DESCRIPTIONS[field.key]}</p>
              </div>
              <Switch
                size="sm"
                checked={field.visible}
                disabled={field.locked || !isIntakeEnabled}
                aria-label={`Show ${field.label} on the request form`}
                onCheckedChange={(checked) => void handleFieldToggle(field, checked)}
              />
            </div>
          ))}
        </div>
      </div>

      <ConfirmDialog
        isOpen={isResetOpen}
        handleClose={() => setIsResetOpen(false)}
        handleSubmit={async () => {
          setIsResetOpen(false);
          try {
            await mutateForm(intakeFormService.resetLink(workspaceSlug, projectId), { revalidate: false });
            setToast({
              type: "success",
              title: "New link created",
              message: "The old link no longer works. Use Resend to email clients the new one.",
            });
          } catch (error) {
            setToast({ type: "error", title: "Error!", message: errorMessage(error, "The link could not be reset.") });
          }
        }}
        title="Reset the request link?"
        content="A new link is created and the current one stops working. Invited clients need the new link to send requests."
        isSubmitting={false}
        primaryButtonText={{ default: "Reset link" }}
      />
      <ConfirmDialog
        isOpen={!!toRemove}
        handleClose={() => setToRemove(null)}
        handleSubmit={async () => {
          const invite = toRemove;
          setToRemove(null);
          if (!invite) return;
          try {
            await intakeFormService.removeInvite(workspaceSlug, projectId, invite.id);
            await mutateInvites();
          } catch (error) {
            setToast({
              type: "error",
              title: "Error!",
              message: errorMessage(error, "The client could not be removed."),
            });
          }
        }}
        title={`Remove ${toRemove?.email ?? ""}?`}
        content="They can no longer send requests to this project. Requests they already sent stay in Intake."
        isSubmitting={false}
        primaryButtonText={{ default: "Remove" }}
      />
    </div>
  );
}
