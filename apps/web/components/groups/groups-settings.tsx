/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { Switch } from "@makeplane/propel/components/switch";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { groupQueueService, useWorkspaceGroups, useWorkspaceQueues } from "@/hooks/use-groups-queues";
import type { TGroupPermission, TWorkspaceGroup } from "@/services/group-queue.service";

type Props = { workspaceSlug: string; isEditable: boolean };

type TDraft = Pick<TWorkspaceGroup, "name" | "description" | "has_queue" | "permissions" | "member_ids">;

const EMPTY_DRAFT: TDraft = {
  name: "",
  description: "",
  has_queue: true,
  permissions: ["queue.view", "queue.self_assign", "queue.edit_assigned"],
  member_ids: [],
};

const toDraft = (group: TWorkspaceGroup): TDraft => ({
  name: group.name,
  description: group.description,
  has_queue: group.has_queue,
  permissions: group.permissions,
  member_ids: group.member_ids,
});

const errorMessage = (error: unknown, fallback: string) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string" ? error.error : fallback;

type EditorProps = {
  draft: TDraft;
  onChange: (draft: TDraft) => void;
  permissions: TGroupPermission[];
  disabled: boolean;
};

function GroupEditor({ draft, onChange, permissions, disabled }: EditorProps) {
  const togglePermission = (key: string, checked: boolean) =>
    onChange({
      ...draft,
      permissions: checked ? [...draft.permissions, key] : draft.permissions.filter((item) => item !== key),
    });
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div className="space-y-3">
        <InputGroup size="md">
          <Input
            size="md"
            value={draft.name}
            onChange={(event) => onChange({ ...draft, name: event.target.value })}
            placeholder="Group name, e.g. DevOps"
            aria-label="Group name"
            disabled={disabled}
            maxLength={255}
          />
        </InputGroup>
        <InputGroup size="md">
          <Input
            size="md"
            value={draft.description}
            onChange={(event) => onChange({ ...draft, description: event.target.value })}
            placeholder="What does this group handle?"
            aria-label="Description"
            disabled={disabled}
          />
        </InputGroup>
        <div className="flex items-center justify-between gap-2 rounded-md border border-subtle px-3 py-2">
          <div>
            <p className="text-body-xs-medium text-primary">Has a queue</p>
            <p className="text-caption-md-regular text-tertiary">Projects can send work items to this group.</p>
          </div>
          <Switch
            size="sm"
            checked={draft.has_queue}
            onCheckedChange={(checked) => onChange({ ...draft, has_queue: checked })}
            disabled={disabled}
            aria-label="Has a queue"
          />
        </div>
        <div>
          <p className="mb-1 text-body-xs-medium text-secondary">Members</p>
          <MemberSelect
            value={draft.member_ids}
            onChange={(ids) => onChange({ ...draft, member_ids: ids })}
            multiple
            variant="select-ghost-md"
            placeholder="Add people"
            disabled={disabled}
            showLabel={draft.member_ids.length <= 2}
            tooltip={{ heading: "Members" }}
          />
        </div>
      </div>
      <fieldset className="space-y-2" disabled={disabled}>
        <legend className="mb-1 text-body-xs-medium text-secondary">Rights</legend>
        {permissions.map((permission) => (
          <label key={permission.key} className="flex cursor-pointer gap-2 rounded-md border border-subtle px-3 py-2">
            <input
              type="checkbox"
              className="mt-0.5"
              aria-label={permission.label}
              checked={draft.permissions.includes(permission.key)}
              onChange={(event) => togglePermission(permission.key, event.target.checked)}
            />
            <span>
              <span className="block text-body-xs-medium text-primary">{permission.label}</span>
              <span className="block text-caption-md-regular text-tertiary">{permission.description}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}

function GroupCard(props: {
  workspaceSlug: string;
  group: TWorkspaceGroup;
  permissions: TGroupPermission[];
  isEditable: boolean;
  onSaved: () => void;
}) {
  const { workspaceSlug, group, permissions, isEditable, onSaved } = props;
  const [draft, setDraft] = useState<TDraft>(toDraft(group));
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  useEffect(() => setDraft(toDraft(group)), [group]);
  const isDirty = JSON.stringify(draft) !== JSON.stringify(toDraft(group));

  const save = async () => {
    setBusy(true);
    try {
      await groupQueueService.updateGroup(workspaceSlug, group.id, draft);
      onSaved();
      setToast({ type: "success", title: "Group saved", message: draft.name });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The group could not be saved.") });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    try {
      await groupQueueService.deleteGroup(workspaceSlug, group.id);
      onSaved();
      setToast({ type: "success", title: "Group deleted", message: group.name });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The group could not be deleted.") });
    }
  };

  return (
    <div className="rounded-lg border border-subtle p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ backgroundColor: group.color }} />
          <h3 className="text-body-sm-medium text-primary">{group.name}</h3>
          <span className="text-caption-md-regular text-tertiary">
            {group.member_ids.length} {group.member_ids.length === 1 ? "member" : "members"}
            {group.has_queue ? " · has a queue" : ""}
          </span>
        </div>
        {isEditable && (
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label="Delete"
              onClick={() => setConfirmDelete(true)}
            />
            <Button
              variant="primary"
              size="sm"
              stretch="auto"
              label={busy ? "Saving..." : "Save"}
              disabled={!isDirty || busy || !draft.name.trim()}
              onClick={() => void save()}
            />
          </div>
        )}
      </div>
      <GroupEditor draft={draft} onChange={setDraft} permissions={permissions} disabled={!isEditable || busy} />
      <ConfirmDialog
        isOpen={confirmDelete}
        handleClose={() => setConfirmDelete(false)}
        handleSubmit={async () => {
          setConfirmDelete(false);
          await remove();
        }}
        title={`Delete the ${group.name} group?`}
        content="Its members lose its rights and the work items in its queue leave the queue. The work items themselves are kept."
        isSubmitting={false}
        primaryButtonText={{ default: "Delete group" }}
      />
    </div>
  );
}

/** Settings → Groups & queues: groups such as DevOps, their rights, members and queue. */
export const GroupsSettings = observer(function GroupsSettings(props: Props) {
  const { workspaceSlug, isEditable } = props;
  const { groups, permissions, mutate } = useWorkspaceGroups(workspaceSlug);
  const { mutate: refreshQueues } = useWorkspaceQueues(workspaceSlug);
  const [newDraft, setNewDraft] = useState<TDraft | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = () => {
    void mutate();
    void refreshQueues();
  };

  const create = async () => {
    if (!newDraft) return;
    setCreating(true);
    try {
      await groupQueueService.createGroup(workspaceSlug, newDraft);
      setNewDraft(null);
      refresh();
      setToast({ type: "success", title: "Group created", message: newDraft.name });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The group could not be created.") });
    } finally {
      setCreating(false);
    }
  };

  if (!groups || !permissions) return <p className="text-body-xs-regular text-tertiary">Loading groups...</p>;

  return (
    <div className="space-y-4">
      {isEditable && !newDraft && (
        <Button variant="primary" size="md" stretch="auto" label="New group" onClick={() => setNewDraft(EMPTY_DRAFT)} />
      )}
      {newDraft && (
        <div className="rounded-lg border border-accent-strong p-4">
          <h3 className="mb-4 text-body-sm-medium text-primary">New group</h3>
          <GroupEditor draft={newDraft} onChange={setNewDraft} permissions={permissions} disabled={creating} />
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" size="sm" stretch="auto" label="Cancel" onClick={() => setNewDraft(null)} />
            <Button
              variant="primary"
              size="sm"
              stretch="auto"
              label={creating ? "Creating..." : "Create group"}
              disabled={creating || !newDraft.name.trim()}
              onClick={() => void create()}
            />
          </div>
        </div>
      )}
      {groups.map((group) => (
        <GroupCard
          key={group.id}
          workspaceSlug={workspaceSlug}
          group={group}
          permissions={permissions}
          isEditable={isEditable}
          onSaved={refresh}
        />
      ))}
    </div>
  );
});
