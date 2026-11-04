/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Checkbox } from "@makeplane/propel/components/checkbox";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { EUserPermissions } from "@plane/constants";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { cn } from "@plane/utils";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { useMember } from "@/hooks/store/use-member";
// services
import type {
  TAccessAction,
  TAccessFeature,
  TAccessRole,
  TPersonAccess,
  TWorkspaceAccess,
} from "@/services/workspace-access.service";
import { workspaceAccessService } from "@/services/workspace-access.service";

const ACTION_ORDER: TAccessAction[] = ["view", "create", "edit", "delete"];
const ACTION_NAMES: Record<TAccessAction, string> = { view: "View", create: "Create", edit: "Edit", delete: "Delete" };
const SCOPES: { key: TAccessFeature["scope"]; label: string }[] = [
  { key: "project", label: "In projects" },
  { key: "workspace", label: "Workspace" },
];
const ROLE_DESCRIPTIONS: Record<TAccessRole, string> = {
  sub_admin: "Members who also create projects and invite people as Member or Client.",
  member: "People who work in the projects they are added to.",
  client: "Clients see the projects they are added to; requests come in through Intake.",
};

const errorMessage = (error: unknown, fallback: string) => (error as { error?: string } | undefined)?.error ?? fallback;

/** The role's value of a cell: what an admin set, else the built-in rule */
const roleValue = (access: TWorkspaceAccess, role: TAccessRole, feature: string, action: TAccessAction) =>
  access.rules[role]?.[feature]?.[action] ?? access.defaults[role][feature][action];

/** Unsaved changes: "feature.action" → allowed */
type TDraft = Record<string, boolean>;
const cellKey = (feature: string, action: TAccessAction) => `${feature}.${action}`;
const splitKey = (key: string) => key.split(".") as [string, TAccessAction];

type TCardsProps = {
  features: TAccessFeature[];
  /** what applies now, before the unsaved changes */
  saved: (feature: TAccessFeature, action: TAccessAction) => boolean;
  /** what they get without the admin's change (the built-in rule, or the role for a person) */
  base: (feature: TAccessFeature, action: TAccessAction) => boolean;
  draft: TDraft;
  onDraftChange: (draft: TDraft) => void;
  changedLabel: string;
};

/**
 * One card per feature, a checkbox per action saying what it does: checked is allowed — the feature and its
 * buttons show — unchecked is denied and hidden. The card's own checkbox allows or denies every action at once.
 */
function PermissionCards(props: TCardsProps) {
  const { features, saved, base, draft, onDraftChange, changedLabel } = props;
  const value = (feature: TAccessFeature, action: TAccessAction) =>
    draft[cellKey(feature.key, action)] ?? saved(feature, action);
  const set = (next: TDraft, feature: TAccessFeature, action: TAccessAction, allowed: boolean) => {
    const key = cellKey(feature.key, action);
    // back to what is saved: nothing to change
    if (allowed === saved(feature, action)) delete next[key];
    else next[key] = allowed;
  };
  const toggle = (feature: TAccessFeature, actions: TAccessAction[], allowed: boolean) => {
    const next = { ...draft };
    actions.forEach((action) => set(next, feature, action, allowed));
    onDraftChange(next);
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-caption-sm-regular text-tertiary">
        <span>
          <span className="font-medium text-secondary">Checked</span> — allowed: the feature and its buttons show
        </span>
        <span>
          <span className="font-medium text-secondary">Unchecked</span> — denied: hidden in every project and refused
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-accent-primary" /> {changedLabel}
        </span>
      </div>
      {SCOPES.map((scope) => {
        const cards = features.filter((feature) => feature.scope === scope.key);
        if (!cards.length) return null;
        return (
          <section key={scope.key} className="flex flex-col gap-2">
            <h4 className="text-caption-md-medium text-placeholder uppercase">{scope.label}</h4>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {cards.map((feature) => {
                const actions = ACTION_ORDER.filter((action) => feature.actions.includes(action));
                const allowedCount = actions.filter((action) => value(feature, action)).length;
                return (
                  <div key={feature.key} className="flex flex-col gap-3 rounded-lg border border-subtle p-4">
                    <div className="flex flex-col gap-1">
                      <Checkbox
                        label={feature.label}
                        checked={allowedCount === actions.length}
                        indeterminate={allowedCount > 0 && allowedCount < actions.length}
                        onCheckedChange={(checked) => toggle(feature, actions, checked)}
                      />
                      <p className="pl-6 text-caption-sm-regular text-tertiary">{feature.description}</p>
                    </div>
                    <div className="flex flex-col gap-2 pl-1">
                      {feature.always_visible && (
                        <p className="text-caption-md-regular text-placeholder">
                          <span className="font-medium">View</span> — always visible: the work item screens need it
                        </p>
                      )}
                      {actions.map((action) => {
                        const allowed = value(feature, action);
                        const changed = allowed !== base(feature, action);
                        const what = feature.action_labels[action] ?? `${ACTION_NAMES[action]} ${feature.label}`;
                        return (
                          <div key={action} className="flex items-start gap-2">
                            <Checkbox
                              checked={allowed}
                              onCheckedChange={(checked) => toggle(feature, [action], checked)}
                              aria-label={`${feature.label}: ${what}`}
                            />
                            <button
                              type="button"
                              className={cn(
                                "-mt-0.5 flex-1 text-left text-body-xs-regular",
                                allowed ? "text-primary" : "text-tertiary"
                              )}
                              onClick={() => toggle(feature, [action], !allowed)}
                            >
                              <span className="font-medium">{ACTION_NAMES[action]}</span> — {what}
                            </button>
                            <span
                              title={changed ? changedLabel : undefined}
                              className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", changed && "bg-accent-primary")}
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/** The unsaved changes as cells */
const draftCells = (draft: TDraft) =>
  Object.entries(draft).map(([key, allowed]) => {
    const [feature, action] = splitKey(key);
    return { feature, action, allowed };
  });

type TRolesProps = { workspaceSlug: string; access: TWorkspaceAccess; onChange: () => Promise<unknown> };

function RolesTab(props: TRolesProps) {
  const { workspaceSlug, access, onChange } = props;
  const [role, setRole] = useState<TAccessRole>("member");
  const [draft, setDraft] = useState<TDraft>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isResetOpen, setIsResetOpen] = useState(false);
  const roleLabel = access.roles.find((item) => item.key === role)?.label ?? "";
  const changes = Object.values(access.rules[role] ?? {}).reduce(
    (count, cells) => count + Object.keys(cells).length,
    0
  );
  const unsaved = Object.keys(draft).length;

  const pickRole = (next: TAccessRole) => {
    setRole(next);
    setDraft({});
  };

  const save = async () => {
    setIsSaving(true);
    try {
      await workspaceAccessService.setRoleCells(workspaceSlug, role, draftCells(draft));
      setDraft({});
      setToast({ type: "success", title: "Saved", message: `${roleLabel} permissions are saved.` });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be changed.") });
    } finally {
      await onChange();
      setIsSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Role">
          <span className="rounded-md border border-subtle bg-layer-1 px-3 py-1.5 text-body-xs-medium text-placeholder">
            Admin · full access
          </span>
          {access.roles.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={role === item.key}
              onClick={() => pickRole(item.key)}
              className={cn(
                "rounded-md border px-3 py-1.5 text-body-xs-medium",
                role === item.key
                  ? "border-accent-strong bg-accent-subtle text-accent-primary"
                  : "border-subtle text-secondary hover:bg-layer-transparent-hover"
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          size="sm"
          stretch="auto"
          label={changes ? `Reset to built-in (${changes})` : "Built-in rules"}
          disabled={!changes}
          onClick={() => setIsResetOpen(true)}
        />
      </div>
      <p className="text-caption-md-regular text-tertiary">
        {ROLE_DESCRIPTIONS[role]} Check what {roleLabel}s may do and save. It applies in every project — new or cloned
        from Jira — and what is unchecked is hidden from them.
      </p>
      <PermissionCards
        features={access.features}
        saved={(feature, action) => roleValue(access, role, feature.key, action)}
        base={(feature, action) => access.defaults[role][feature.key][action]}
        draft={draft}
        onDraftChange={setDraft}
        changedLabel="Changed from the built-in rule"
      />
      <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-subtle bg-surface-1 py-3">
        <span className="mr-auto text-caption-md-regular text-tertiary">
          {unsaved ? `${unsaved} unsaved ${unsaved === 1 ? "change" : "changes"}` : "No unsaved changes"}
        </span>
        <Button
          variant="secondary"
          size="md"
          stretch="auto"
          label="Cancel"
          disabled={!unsaved || isSaving}
          onClick={() => setDraft({})}
        />
        <Button
          variant="primary"
          size="md"
          stretch="auto"
          label={isSaving ? "Saving…" : "Save"}
          disabled={!unsaved || isSaving}
          onClick={() => void save()}
        />
      </div>
      <ConfirmDialog
        isOpen={isResetOpen}
        handleClose={() => setIsResetOpen(false)}
        handleSubmit={async () => {
          setIsResetOpen(false);
          try {
            await workspaceAccessService.resetRole(workspaceSlug, role);
            setDraft({});
            await onChange();
          } catch (error) {
            setToast({ type: "error", title: "Error!", message: errorMessage(error, "The role could not be reset.") });
          }
        }}
        title={`Reset ${roleLabel} to the built-in rules?`}
        content="Every change made to this role is removed. Custom access given to people stays."
        isSubmitting={false}
        primaryButtonText={{ default: "Reset" }}
      />
    </div>
  );
}

/** How many cells a person's custom access changes */
const changeCount = (target: TPersonAccess) =>
  Object.values(target.custom_access).reduce((count, cells) => count + Object.keys(cells).length, 0);

type TPeopleProps = { workspaceSlug: string; access: TWorkspaceAccess; onChange: () => Promise<unknown> };

type TPersonDialogProps = {
  workspaceSlug: string;
  access: TWorkspaceAccess;
  memberId: string | null;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
};

/** "Permissions for Riya Shah": their role's permissions with their custom access, saved together */
const PersonPermissionsDialog = observer(function PersonPermissionsDialog(props: TPersonDialogProps) {
  const { workspaceSlug, access, memberId, onClose, onSaved } = props;
  const [draft, setDraft] = useState<TDraft>({});
  const [isSaving, setIsSaving] = useState(false);
  const { data: person, mutate } = useSWR(memberId ? ["WORKSPACE_ACCESS_PERSON", workspaceSlug, memberId] : null, () =>
    workspaceAccessService.fetchPerson(workspaceSlug, memberId ?? "")
  );
  const role = person && person.role !== "admin" ? person.role : undefined;
  const unsaved = Object.keys(draft).length;

  const close = () => {
    setDraft({});
    onClose();
  };

  const save = async () => {
    if (!person || !role) return;
    setIsSaving(true);
    try {
      await workspaceAccessService.setPersonCells(
        workspaceSlug,
        person.member_id,
        draftCells(draft).map(({ feature, action, allowed }) => ({
          feature,
          action,
          // the same as their role: no custom access for this cell
          value: allowed === roleValue(access, role, feature, action) ? "default" : allowed ? "allow" : "deny",
        }))
      );
      setToast({
        type: "success",
        title: "Saved",
        message: `Permissions for ${person.full_name || person.display_name} are saved.`,
      });
      await Promise.all([mutate(), onSaved()]);
      close();
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be changed.") });
    } finally {
      setIsSaving(false);
    }
  };

  const resetToRole = async () => {
    if (!person) return;
    try {
      await workspaceAccessService.resetPerson(workspaceSlug, person.member_id);
      await Promise.all([mutate(), onSaved()]);
      setDraft({});
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be reset.") });
    }
  };

  return (
    <Dialog open={!!memberId} onOpenChange={(open) => !open && close()}>
      <DialogContent size="full" density="compact">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>Permissions for {person ? person.full_name || person.display_name : "…"}</DialogTitle>
              <DialogDescription>
                {person
                  ? `${person.email ? `${person.email} · ` : ""}${access.roles.find((item) => item.key === role)?.label ?? "Admin"}. `
                  : ""}
                Starts from their role; what you change here applies to them only, in every project.
              </DialogDescription>
            </DialogHeading>
          </DialogHeader>
          <DialogBody tabIndex={0}>
            {person && role ? (
              <PermissionCards
                features={access.features}
                saved={(feature, action) =>
                  person.custom_access[feature.key]?.[action] ?? roleValue(access, role, feature.key, action)
                }
                base={(feature, action) => roleValue(access, role, feature.key, action)}
                draft={draft}
                onDraftChange={setDraft}
                changedLabel="Changed from their role"
              />
            ) : person ? (
              <p className="text-body-xs-regular text-tertiary">Admins always have full access.</p>
            ) : null}
          </DialogBody>
        </DialogMain>
        <DialogActions>
          {person && role && changeCount(person) > 0 && (
            <div className="mr-auto">
              <Button
                variant="ghost"
                size="md"
                stretch="auto"
                label={`Reset to their role (${changeCount(person)})`}
                onClick={() => void resetToRole()}
              />
            </div>
          )}
          <Button variant="secondary" size="md" stretch="auto" label="Cancel" onClick={close} />
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label={isSaving ? "Saving…" : "Save"}
            disabled={!unsaved || isSaving}
            onClick={() => void save()}
          />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
});

const PeopleTab = observer(function PeopleTab(props: TPeopleProps) {
  const { workspaceSlug, access, onChange } = props;
  const [openId, setOpenId] = useState<string | null>(null);
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails },
  } = useMember();
  const { data: people, mutate: mutatePeople } = useSWR(["WORKSPACE_ACCESS_PEOPLE", workspaceSlug], () =>
    workspaceAccessService.fetchPeople(workspaceSlug)
  );
  // admins always have full access: only the others get custom access
  const memberIds = useMemo(
    () =>
      (workspaceMemberIds ?? []).filter((id) => {
        const details = getWorkspaceMemberDetails(id);
        return details?.is_active !== false && details?.role !== EUserPermissions.ADMIN;
      }),
    [workspaceMemberIds, getWorkspaceMemberDetails]
  );

  const reset = async (target: TPersonAccess) => {
    try {
      await workspaceAccessService.resetPerson(workspaceSlug, target.member_id);
      await Promise.all([mutatePeople(), onChange()]);
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be reset.") });
    }
  };

  const roleLabel = (role: TPersonAccess["role"]) =>
    role === "admin" ? "Admin" : (access.roles.find((item) => item.key === role)?.label ?? role);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-caption-md-regular text-tertiary">
        Give one person more or less than their role: choose them to open their permissions, check or uncheck, and save.
        Unchecking something their role allows hides it from them only.
      </p>
      <div className="w-72">
        <MemberSelect
          variant="select-md"
          memberIds={memberIds}
          value={null}
          onChange={(id) => id && setOpenId(id)}
          placeholder="Choose a person"
        />
      </div>
      <div className="flex flex-col gap-2">
        <h4 className="text-body-sm-medium text-primary">People with custom access</h4>
        {people && people.length > 0 ? (
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {people.map((item) => (
              <div key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body-xs-medium text-primary">{item.full_name || item.display_name}</p>
                  <p className="truncate text-caption-sm-regular text-tertiary">
                    {item.email ? `${item.email} · ` : ""}
                    {roleLabel(item.role)} · {changeCount(item)} {changeCount(item) === 1 ? "change" : "changes"}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  stretch="auto"
                  label="Edit permissions"
                  onClick={() => setOpenId(item.member_id)}
                />
                <Button variant="ghost" size="sm" stretch="auto" label="Remove" onClick={() => void reset(item)} />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-caption-md-regular text-placeholder">Nobody has custom access yet.</p>
        )}
      </div>
      <PersonPermissionsDialog
        workspaceSlug={workspaceSlug}
        access={access}
        memberId={openId}
        onClose={() => setOpenId(null)}
        onSaved={() => Promise.all([mutatePeople(), onChange()])}
      />
    </div>
  );
});

type Props = { workspaceSlug: string };

/** Settings → Roles & access, for workspace admins */
export const WorkspaceAccessRoot = observer(function WorkspaceAccessRoot(props: Props) {
  const { workspaceSlug } = props;
  const [tab, setTab] = useState<"roles" | "people">("roles");
  const { data: access, mutate } = useSWR(workspaceSlug ? ["WORKSPACE_ACCESS", workspaceSlug] : null, () =>
    workspaceAccessService.fetch(workspaceSlug)
  );
  if (!access) return null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex gap-1 border-b border-subtle" role="tablist">
        {(
          [
            ["roles", "Roles"],
            ["people", `Custom access${access.custom_count ? ` (${access.custom_count})` : ""}`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={cn(
              "-mb-px border-b-2 px-4 py-2 text-body-xs-medium",
              tab === key ? "border-accent-strong text-accent-primary" : "border-transparent text-tertiary"
            )}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "roles" ? (
        <RolesTab workspaceSlug={workspaceSlug} access={access} onChange={() => mutate()} />
      ) : (
        <PeopleTab workspaceSlug={workspaceSlug} access={access} onChange={() => mutate()} />
      )}
    </div>
  );
});
