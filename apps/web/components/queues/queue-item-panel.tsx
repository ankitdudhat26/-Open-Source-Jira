/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { CloseOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import { ISSUE_PRIORITIES } from "@plane/constants";
import { renderFormattedDate } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useUserPermissions } from "@/hooks/store/user";
import { groupQueueService } from "@/hooks/use-groups-queues";

type Props = {
  workspaceSlug: string;
  groupId: string;
  issueId: string;
  onClose: () => void;
  /** a change was saved, refresh the lists and counts */
  onChanged: () => void;
};

const errorMessage = (error: unknown, fallback: string) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string" ? error.error : fallback;

const FIELD = "w-full rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] items-center gap-2 py-1.5">
      <span className="text-caption-md-regular text-tertiary">{label}</span>
      <div className="min-w-0 text-body-xs-regular text-primary">{children}</div>
    </div>
  );
}

/** A queue work item: read only until you take it, then status, priority, dates and comments can be changed. */
export const QueueItemPanel = observer(function QueueItemPanel(props: Props) {
  const { workspaceSlug, groupId, issueId, onClose, onChanged } = props;
  const { getUserDetails } = useMember();
  const { workspaceProjectsPermissions } = useUserPermissions();
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");

  const { data: item, mutate } = useSWR(`QUEUE_ITEM_${groupId}_${issueId}`, () =>
    groupQueueService.getQueueItem(workspaceSlug, groupId, issueId)
  );

  const run = async (action: () => Promise<unknown>, success: string, fallback: string) => {
    setBusy(true);
    try {
      await action();
      await mutate();
      onChanged();
      setToast({ type: "success", title: success, message: item ? `${item.key} ${item.name}` : "" });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, fallback) });
    } finally {
      setBusy(false);
    }
  };

  const update = (data: Parameters<typeof groupQueueService.updateQueueItem>[3]) =>
    run(
      () => groupQueueService.updateQueueItem(workspaceSlug, groupId, issueId, data),
      "Work item updated",
      "The work item could not be updated."
    );

  const isProjectMember = !!item && !!workspaceProjectsPermissions?.[workspaceSlug]?.[item.project.id];

  return (
    <aside
      className="flex h-full w-full max-w-md shrink-0 flex-col border-l border-subtle bg-surface-1"
      aria-label="Queue work item"
    >
      <div className="flex items-center justify-between gap-2 border-b border-subtle px-4 py-3">
        <span className="truncate text-caption-md-medium text-tertiary">
          {item ? `${item.project.name} · ${item.key}` : "Loading..."}
        </span>
        <IconButton variant="ghost" size="sm" icon={<CloseOutline />} aria-label="Close" onClick={onClose} />
      </div>

      {item && (
        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
          <div>
            <h2 className="text-h5-medium break-words text-primary">{item.name}</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {item.can_self_assign && (
                <Button
                  variant="primary"
                  size="sm"
                  stretch="auto"
                  label="Assign to me"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => groupQueueService.assignToMe(workspaceSlug, groupId, issueId),
                      "Assigned to you",
                      "The work item could not be assigned."
                    )
                  }
                />
              )}
              {item.is_mine && (
                <Button
                  variant="secondary"
                  size="sm"
                  stretch="auto"
                  label="Unassign me"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => groupQueueService.unassignMe(workspaceSlug, groupId, issueId),
                      "Unassigned",
                      "Could not unassign you."
                    )
                  }
                />
              )}
              {isProjectMember && (
                <Link
                  href={`/${workspaceSlug}/projects/${item.project.id}/issues/${item.id}`}
                  className="inline-flex items-center rounded-md border border-subtle px-2.5 text-body-xs-medium text-secondary hover:bg-layer-transparent-hover"
                >
                  Open in project
                </Link>
              )}
            </div>
            {!item.can_edit && !item.can_self_assign && !item.is_mine && (
              <p className="mt-2 text-caption-md-regular text-tertiary">Read only.</p>
            )}
            {!item.can_edit && item.can_self_assign && (
              <p className="mt-2 text-caption-md-regular text-tertiary">
                Read only. Assign it to yourself to work on it.
              </p>
            )}
          </div>

          <div className="divide-y divide-subtle rounded-md border border-subtle px-3">
            <Row label="Status">
              {item.can_edit ? (
                <select
                  className={FIELD}
                  value={item.state?.id ?? ""}
                  disabled={busy}
                  aria-label="Status"
                  onChange={(event) => void update({ state_id: event.target.value })}
                >
                  {item.states.map((state) => (
                    <option key={state.id} value={state.id}>
                      {state.name}
                    </option>
                  ))}
                </select>
              ) : (
                (item.state?.name ?? "—")
              )}
            </Row>
            <Row label="Priority">
              {item.can_edit ? (
                <select
                  className={FIELD}
                  value={item.priority ?? "none"}
                  disabled={busy}
                  aria-label="Priority"
                  onChange={(event) => void update({ priority: event.target.value })}
                >
                  {ISSUE_PRIORITIES.map((priority) => (
                    <option key={priority.key} value={priority.key}>
                      {priority.title}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="capitalize">{item.priority ?? "none"}</span>
              )}
            </Row>
            <Row label="Assignee">
              {item.assignee_ids.length
                ? item.assignee_ids.map((id) => getUserDetails(id)?.display_name ?? "Member").join(", ")
                : "Unassigned"}
            </Row>
            <Row label="Start date">
              {item.can_edit ? (
                <input
                  type="date"
                  className={FIELD}
                  value={item.start_date ?? ""}
                  disabled={busy}
                  aria-label="Start date"
                  onChange={(event) => void update({ start_date: event.target.value || null })}
                />
              ) : item.start_date ? (
                renderFormattedDate(item.start_date)
              ) : (
                "—"
              )}
            </Row>
            <Row label="Due date">
              {item.can_edit ? (
                <input
                  type="date"
                  className={FIELD}
                  value={item.target_date ?? ""}
                  disabled={busy}
                  aria-label="Due date"
                  onChange={(event) => void update({ target_date: event.target.value || null })}
                />
              ) : item.target_date ? (
                renderFormattedDate(item.target_date)
              ) : (
                "—"
              )}
            </Row>
            {item.type && <Row label="Type">{item.type}</Row>}
            {item.parent && <Row label="Parent">{`${item.parent.key} ${item.parent.name}`}</Row>}
            {item.labels.length > 0 && <Row label="Labels">{item.labels.join(", ")}</Row>}
            <Row label="Created">{renderFormattedDate(item.created_at)}</Row>
          </div>

          <div>
            <h3 className="mb-1.5 text-body-xs-medium text-secondary">Description</h3>
            <p className="text-body-xs-regular whitespace-pre-wrap text-primary">
              {item.description || <span className="text-tertiary">No description.</span>}
            </p>
          </div>

          <div>
            <h3 className="mb-2 text-body-xs-medium text-secondary">Comments</h3>
            <div className="space-y-2">
              {item.comments.length === 0 && <p className="text-caption-md-regular text-tertiary">No comments yet.</p>}
              {item.comments.map((entry) => (
                <div key={entry.id} className="rounded-md bg-layer-2 px-3 py-2">
                  <p className="text-caption-md-medium text-secondary">
                    {entry.actor} · <span className="text-tertiary">{renderFormattedDate(entry.created_at)}</span>
                  </p>
                  <p className="mt-0.5 text-body-xs-regular whitespace-pre-wrap text-primary">{entry.comment}</p>
                </div>
              ))}
            </div>
            {item.can_comment && (
              <form
                className="mt-3 space-y-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!comment.trim()) return;
                  void run(
                    () => groupQueueService.addComment(workspaceSlug, groupId, issueId, comment),
                    "Comment added",
                    "The comment could not be added."
                  ).then(() => setComment(""));
                }}
              >
                <textarea
                  className={`${FIELD} min-h-20`}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Add a comment"
                  aria-label="Add a comment"
                />
                <Button
                  variant="primary"
                  size="sm"
                  stretch="auto"
                  type="submit"
                  label="Comment"
                  disabled={busy || !comment.trim()}
                />
              </form>
            )}
          </div>
        </div>
      )}
    </aside>
  );
});
