/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { Switch } from "@makeplane/propel/components/switch";
import { ROLE } from "@plane/constants";
import type { EUserPermissions } from "@plane/constants";
import { setToast } from "@plane/blocks/toast";
import { getFileURL } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import type { TIntakeForm } from "@/services/intake-form.service";
import { intakeFormService } from "@/services/intake-form.service";

type Props = {
  workspaceSlug: string;
  projectId: string;
  form: TIntakeForm;
  /** saves the form returned by the server (or reverts on an error) */
  mutateForm: (data: Promise<TIntakeForm>, optimistic: TIntakeForm) => Promise<unknown>;
  disabled?: boolean;
};

/**
 * Settings → Intake: who is emailed when a client sends a request on the link. Every member of the project is listed
 * (as in Members), each with a switch; nobody is emailed until switched on.
 */
export const IntakeReceivedEmails = observer(function IntakeReceivedEmails(props: Props) {
  const { workspaceSlug, projectId, form, mutateForm, disabled = false } = props;
  const {
    project: { getProjectMemberIds, getProjectMemberDetails, fetchProjectMembers },
  } = useMember();

  // the Members list of the project (loaded here when the settings are opened directly)
  useSWR(workspaceSlug && projectId ? ["PROJECT_MEMBERS_FOR_INTAKE_EMAILS", projectId] : null, () =>
    fetchProjectMembers(workspaceSlug, projectId)
  );
  const memberIds = getProjectMemberIds(projectId, true) ?? [];
  const members = memberIds
    .map((id) => getProjectMemberDetails(id, projectId))
    .filter((member): member is NonNullable<typeof member> => !!member);
  const selected = new Set(form.notify_member_ids ?? []);

  const toggle = async (memberId: string, isOn: boolean) => {
    const next = isOn ? [...selected, memberId] : [...selected].filter((id) => id !== memberId);
    try {
      await mutateForm(intakeFormService.update(workspaceSlug, projectId, { notify_member_ids: next }), {
        ...form,
        notify_member_ids: next,
      });
    } catch {
      setToast({ type: "error", title: "Error!", message: "The email setting could not be saved. Try again." });
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h4 className="text-body-sm-medium text-primary">Intake received emails</h4>
          <p className="text-caption-md-regular text-tertiary">
            When a client sends a request on the link, the members switched on here get an email with the request and a
            link to open it in Intake. Everyone is off until you switch them on.
          </p>
        </div>
        <span className="text-caption-md-regular text-tertiary">
          {selected.size === 0 ? "Nobody is emailed" : `${selected.size} of ${members.length} emailed`}
        </span>
      </div>
      <div className="divide-y divide-subtle rounded-lg border border-subtle">
        {members.length === 0 && (
          <p className="px-4 py-3 text-caption-md-regular text-tertiary">This project has no members yet.</p>
        )}
        {members.map(({ member, original_role, role, designation }) => {
          const name =
            [member.first_name, member.last_name].filter(Boolean).join(" ").trim() || member.display_name || "";
          const roleLabel = ROLE[(original_role ?? role) as EUserPermissions] as string | undefined;
          return (
            <div key={member.id} className="flex items-center gap-3 px-4 py-2.5">
              <Avatar
                size="md"
                src={member.avatar_url ? getFileURL(member.avatar_url) : undefined}
                alt={name}
                fallback={name[0]?.toUpperCase()}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-body-xs-medium text-primary">{name}</p>
                <p className="truncate text-caption-md-regular text-tertiary">
                  {[member.email, designation, roleLabel].filter(Boolean).join(" · ")}
                </p>
              </div>
              <Switch
                size="sm"
                checked={selected.has(member.id)}
                disabled={disabled}
                aria-label={`Email ${name} when a client sends a request`}
                onCheckedChange={(checked) => void toggle(member.id, checked)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
});
