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
import { Switch } from "@makeplane/propel/components/switch";
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

const ACTIONS: { key: TAccessAction; label: string }[] = [
  { key: "view", label: "View" },
  { key: "create", label: "Create" },
  { key: "edit", label: "Edit" },
  { key: "delete", label: "Delete" },
];
const SCOPES: { key: TAccessFeature["scope"]; label: string }[] = [
  { key: "project", label: "In projects" },
  { key: "workspace", label: "Workspace" },
];
const ROLE_DESCRIPTIONS: Record<TAccessRole, string> = {
  sub_admin: "Members who also create projects and invite people as Member or Client.",
  member: "People who work in the projects they are added to.",
  client: "Clients see the projects they are added to; requests come in through Intake.",
};

type TCell = {
  /** what the person or role ends up with */
  allowed: boolean;
  /** changed from what they get otherwise (the built-in rule for a role, the role for a person) */
  changed: boolean;
  /** what they get without the change */
  base: boolean;
};

const errorMessage = (error: unknown, fallback: string) => (error as { error?: string } | undefined)?.error ?? fallback;

/** The role's value of a cell: what an admin set, else the built-in rule */
const roleValue = (access: TWorkspaceAccess, role: TAccessRole, feature: string, action: TAccessAction) =>
  access.rules[role]?.[feature]?.[action] ?? access.defaults[role][feature][action];

type TGridProps = {
  features: TAccessFeature[];
  cell: (feature: TAccessFeature, action: TAccessAction) => TCell;
  onToggle: (feature: TAccessFeature, action: TAccessAction, allowed: boolean) => void;
  changedLabel: string;
};

/** Features × View / Create / Edit / Delete, a switch per cell; a dot marks what differs from the base */
function AccessGrid(props: TGridProps) {
  const { features, cell, onToggle, changedLabel } = props;
  return (
    <div className="overflow-x-auto rounded-lg border border-subtle">
      <table className="w-full min-w-[640px] text-left">
        <thead>
          <tr className="border-b border-subtle bg-layer-1">
            <th className="px-4 py-2.5 text-caption-md-medium text-tertiary">Feature</th>
            {ACTIONS.map((action) => (
              <th key={action.key} className="w-24 px-2 py-2.5 text-center text-caption-md-medium text-tertiary">
                {action.label}
              </th>
            ))}
          </tr>
        </thead>
        {SCOPES.map((scope) => {
          const rows = features.filter((feature) => feature.scope === scope.key);
          if (!rows.length) return null;
          return (
            <tbody key={scope.key} className="divide-y divide-subtle">
              <tr className="bg-layer-1/50">
                <td
                  colSpan={ACTIONS.length + 1}
                  className="px-4 py-1.5 text-caption-sm-medium text-placeholder uppercase"
                >
                  {scope.label}
                </td>
              </tr>
              {rows.map((feature) => (
                <tr key={feature.key}>
                  <td className="px-4 py-2.5">
                    <p className="text-body-xs-medium text-primary">{feature.label}</p>
                    <p className="text-caption-sm-regular text-tertiary">{feature.description}</p>
                  </td>
                  {ACTIONS.map((action) => {
                    if (!feature.actions.includes(action.key))
                      return (
                        <td key={action.key} className="px-2 py-2.5 text-center text-placeholder">
                          —
                        </td>
                      );
                    const value = cell(feature, action.key);
                    return (
                      <td key={action.key} className="px-2 py-2.5">
                        <div className="flex items-center justify-center gap-1.5">
                          <Switch
                            size="sm"
                            checked={value.allowed}
                            onCheckedChange={(checked) => onToggle(feature, action.key, checked)}
                            aria-label={`${action.label} ${feature.label}`}
                          />
                          <span
                            title={value.changed ? `${changedLabel} (${value.base ? "allowed" : "not allowed"})` : ""}
                            className={cn("size-1.5 shrink-0 rounded-full", value.changed ? "bg-accent-primary" : "")}
                          />
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}

type TRolesProps = { workspaceSlug: string; access: TWorkspaceAccess; onChange: () => Promise<unknown> };

function RolesTab(props: TRolesProps) {
  const { workspaceSlug, access, onChange } = props;
  const [role, setRole] = useState<TAccessRole>("member");
  const [isResetOpen, setIsResetOpen] = useState(false);
  const changes = Object.values(access.rules[role] ?? {}).reduce(
    (count, cells) => count + Object.keys(cells).length,
    0
  );

  const toggle = async (feature: TAccessFeature, action: TAccessAction, allowed: boolean) => {
    try {
      await workspaceAccessService.setRoleAccess(workspaceSlug, { role, feature: feature.key, action, allowed });
      await onChange();
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be changed.") });
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
              onClick={() => setRole(item.key)}
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
        {ROLE_DESCRIPTIONS[role]} Turn an action off to block it everywhere, or on to allow it beyond the role. A dot
        marks a change from the built-in rules. Project admins keep full access to their own projects.
      </p>
      <AccessGrid
        features={access.features}
        changedLabel="Changed from the built-in rule"
        cell={(feature, action) => {
          const base = access.defaults[role][feature.key][action];
          const set = access.rules[role]?.[feature.key]?.[action];
          return { allowed: set ?? base, changed: set !== undefined, base };
        }}
        onToggle={(feature, action, allowed) => void toggle(feature, action, allowed)}
      />
      <ConfirmDialog
        isOpen={isResetOpen}
        handleClose={() => setIsResetOpen(false)}
        handleSubmit={async () => {
          setIsResetOpen(false);
          try {
            await workspaceAccessService.resetRole(workspaceSlug, role);
            await onChange();
          } catch (error) {
            setToast({ type: "error", title: "Error!", message: errorMessage(error, "The role could not be reset.") });
          }
        }}
        title={`Reset ${access.roles.find((item) => item.key === role)?.label ?? ""} to the built-in rules?`}
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

const PeopleTab = observer(function PeopleTab(props: TPeopleProps) {
  const { workspaceSlug, access, onChange } = props;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails },
  } = useMember();
  const { data: people, mutate: mutatePeople } = useSWR(["WORKSPACE_ACCESS_PEOPLE", workspaceSlug], () =>
    workspaceAccessService.fetchPeople(workspaceSlug)
  );
  const { data: person, mutate: mutatePerson } = useSWR(
    selectedId ? ["WORKSPACE_ACCESS_PERSON", workspaceSlug, selectedId] : null,
    () => workspaceAccessService.fetchPerson(workspaceSlug, selectedId ?? "")
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

  const refresh = async (next?: TPersonAccess) => {
    if (next) await mutatePerson(next, { revalidate: false });
    await Promise.all([mutatePeople(), onChange()]);
  };

  const toggle = async (target: TPersonAccess, feature: TAccessFeature, action: TAccessAction, allowed: boolean) => {
    if (target.role === "admin") return;
    // back to what their role gets: no custom access for this cell
    const fromRole = roleValue(access, target.role, feature.key, action);
    const value = allowed === fromRole ? "default" : allowed ? "allow" : "deny";
    try {
      await refresh(
        await workspaceAccessService.setPersonAccess(workspaceSlug, target.member_id, {
          feature: feature.key,
          action,
          value,
        })
      );
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be changed.") });
    }
  };

  const reset = async (target: TPersonAccess) => {
    try {
      await refresh(await workspaceAccessService.resetPerson(workspaceSlug, target.member_id));
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The access could not be reset.") });
    }
  };

  const roleLabel = (role: TPersonAccess["role"]) =>
    role === "admin" ? "Admin" : (access.roles.find((item) => item.key === role)?.label ?? role);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-caption-md-regular text-tertiary">
        Give one person more or less than their role: pick them, then turn actions on or off. A dot marks a change from
        their role. Setting a switch back to what the role gets removes the change.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-72">
          <MemberSelect
            variant="select-md"
            memberIds={memberIds}
            value={selectedId}
            onChange={(id) => setSelectedId(id || null)}
            placeholder="Choose a person"
          />
        </div>
        {person && person.role !== "admin" && changeCount(person) > 0 && (
          <Button
            variant="ghost"
            size="sm"
            stretch="auto"
            label={`Remove custom access (${changeCount(person)})`}
            onClick={() => void reset(person)}
          />
        )}
      </div>
      {person && person.role !== "admin" && (
        <div className="flex flex-col gap-2">
          <p className="text-body-xs-regular text-secondary">
            <span className="font-medium text-primary">{person.full_name || person.display_name}</span>
            {person.email ? ` · ${person.email}` : ""} · {roleLabel(person.role)}
          </p>
          <AccessGrid
            features={access.features}
            changedLabel="Changed from their role"
            cell={(feature, action) => {
              const base = roleValue(access, person.role as TAccessRole, feature.key, action);
              const custom = person.custom_access[feature.key]?.[action];
              return { allowed: custom ?? base, changed: custom !== undefined, base };
            }}
            onToggle={(feature, action, allowed) => void toggle(person, feature, action, allowed)}
          />
        </div>
      )}
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
                  label="Edit"
                  onClick={() => setSelectedId(item.member_id)}
                />
                <Button variant="ghost" size="sm" stretch="auto" label="Remove" onClick={() => void reset(item)} />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-caption-md-regular text-placeholder">Nobody has custom access yet.</p>
        )}
      </div>
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
