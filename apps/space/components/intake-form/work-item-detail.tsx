/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useId, useMemo, useState } from "react";
import useSWR from "swr";
// plane imports
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import {
  ArrowNarrowRightOutline,
  CalendarOutline,
  CloseOutline,
  CyclesOutline,
  LabelsOutline,
  LayerStackOutline,
  MembersOutline,
  MilestoneOutline,
  ModuleOutline,
  ParentOutline,
  PriorityOutline,
  SortAscendingOutline,
  SortDescendingOutline,
  StateOutline,
  UserOutline,
} from "@makeplane/propel/icons";
import { PriorityIcon } from "@plane/blocks/icons";
import { StateSelect } from "@plane/blocks/property-select";
import type { StateOption } from "@plane/blocks/property-select";
import { cn, renderFormattedDate } from "@plane/utils";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
// local imports
import { IntakeCommentEditor, IntakeReadOnlyHtml } from "./description-editor";
import type { TStateLite, TWorkItemDetail } from "./portal-shared";
import { FileCards, FileDropZone, addFiles, usePickedPreviews } from "./file-previews";
import type { TPreviewFile } from "./file-previews";
import { LabelChip, PRIORITY_LABELS, getJson, initials, isEmptyHtml, send } from "./portal-shared";

type Props = {
  base: string;
  issueId: string;
  onClose: () => void;
  /** after the client changed it (state, comment, files): the lists refresh */
  onChanged: () => void;
};

type TActivityTab = "all" | "comments" | "history";
type THistory = TWorkItemDetail["history"][number];
type TComment = TWorkItemDetail["comments"][number];
type TEntry = ({ kind: "comment" } & TComment) | ({ kind: "history" } & THistory);

/** "November 19, 2026 at 3:02 PM", as the app's activity shows it */
const activityDate = (value: string) => {
  const date = new Date(value);
  const day = date.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
  const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day} at ${time}`;
};

function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-primary text-caption-md-medium text-on-color",
        className
      )}
    >
      {initials(name)}
    </span>
  );
}

/** A state as a chip in its colour (the app's "Testing / QA → Ready for Deployment") */
function StateChip({ name, state }: { name: string | null; state: TStateLite | undefined }) {
  const color = state?.color ?? "#6B7280";
  return (
    <span
      className="inline-flex items-center rounded-sm border px-1.5 py-0.5 text-caption-md-medium"
      style={{ borderColor: `${color}66`, color, backgroundColor: `${color}14` }}
    >
      {name || "None"}
    </span>
  );
}

function Property({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-9 items-center gap-3">
      <span className="flex w-36 shrink-0 items-center gap-2 text-body-xs-regular text-secondary">
        <span className="flex size-4 items-center justify-center text-tertiary">{icon}</span>
        {label}
      </span>
      <div className="min-w-0 flex-1 text-body-xs-regular text-primary">{children}</div>
    </div>
  );
}

const None = ({ children = "None" }: { children?: string }) => <span className="text-placeholder">{children}</span>;

/** What a history entry says, worded like the app ("changed the Status", "added the Assignee"…) */
function historyLabel(entry: THistory) {
  if (entry.field === null && entry.verb === "created") return "created the work item";
  if (entry.field === "state") return "changed the Status";
  if (entry.field === "intake")
    return entry.new_value === "Accepted"
      ? "accepted this work item from intake."
      : `marked the request ${entry.new_value ?? ""}`.trim();
  if (entry.field === "assignees") return entry.new_value ? "added the Assignee" : "removed the Assignee";
  if (entry.field === "labels") return entry.new_value ? "added the Label" : "removed the Label";
  if (entry.field === "priority") return "changed the Priority";
  if (entry.field === "attachment") return entry.verb === "created" ? "attached a file" : "removed a file";
  return entry.text;
}

/**
 * A work item's details for the client, laid out like the app's work item panel: title, type, description, files,
 * properties and activity (comments and history). The client comments (with files), attaches files and moves it to
 * another state — only to the states the project's workflow lets them; the rest is the team's and only shown.
 */
export function WorkItemDetail({ base, issueId, onClose, onChanged }: Props) {
  const url = `${base}work-items/${issueId}/`;
  const { data: item, error, mutate } = useSWR(url, (key: string) => getJson<TWorkItemDetail>(key));
  const [tab, setTab] = useState<TActivityTab>("all");
  const [newestFirst, setNewestFirst] = useState(true);
  const [comment, setComment] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [editorKey, setEditorKey] = useState(0);
  const [isPosting, setIsPosting] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [isAttaching, setIsAttaching] = useState(false);
  const editorId = useId();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const stateByName = useMemo(() => new Map((item?.states ?? []).map((state) => [state.name, state])), [item]);

  const activity = useMemo<TEntry[]>(() => {
    if (!item) return [];
    const comments: TEntry[] = item.comments.map((entry) => Object.assign({ kind: "comment" as const }, entry));
    const history: TEntry[] = item.history.map((entry) => Object.assign({ kind: "history" as const }, entry));
    const entries = tab === "comments" ? comments : tab === "history" ? history : [...comments, ...history];
    // a sorted copy (toSorted needs ES2023)
    // oxlint-disable-next-line unicorn/no-array-sort
    return [...entries].sort((a, b) =>
      newestFirst ? b.created_at.localeCompare(a.created_at) : a.created_at.localeCompare(b.created_at)
    );
  }, [item, tab, newestFirst]);

  const stateOptions = useMemo<StateOption[]>(() => (item?.state ? [item.state, ...item.allowed_states] : []), [item]);

  const refresh = async () => {
    await mutate();
    onChanged();
  };

  const handleState = async (stateId: string) => {
    if (!item || stateId === item.state?.id) return;
    setMessage(null);
    try {
      await mutate(await send<TWorkItemDetail>(url, "PATCH", { state_id: stateId }), { revalidate: false });
      onChanged();
      setMessage({ kind: "success", text: "State changed." });
    } catch (err) {
      setMessage({ kind: "error", text: (err as Error).message });
    }
  };

  const uploadFiles = async (list: File[]) => {
    const failed: string[] = [];
    for (const file of list) {
      const body = new FormData();
      body.append("file", file);
      // one after another, so the team sees them in order
      // oxlint-disable-next-line no-await-in-loop
      await send(`${url}attachments/`, "POST", body).catch(() => failed.push(file.name));
    }
    return failed;
  };

  // what was picked for the next comment, previewed under it
  const commentPreviews = usePickedPreviews(files);
  const pickForComment = (picked: File[]) => {
    const result = addFiles(files, picked);
    setMessage(result.error ? { kind: "error", text: result.error } : null);
    setFiles(result.files);
  };
  const attachments = useMemo<TPreviewFile[]>(
    () => (item?.attachments ?? []).map((file) => ({ key: file.id, name: file.name, size: file.size, url: file.url })),
    [item]
  );

  const handleComment = async () => {
    if (isEmptyHtml(comment) && files.length === 0) return;
    setIsPosting(true);
    setMessage(null);
    try {
      const failed = await uploadFiles(files);
      const attached = files.filter((file) => !failed.includes(file.name)).map((file) => file.name);
      const text = isEmptyHtml(comment) ? "" : comment;
      const html = `${text}${attached.length ? `<p>Attached: ${attached.join(", ")}</p>` : ""}`;
      if (html) await send(`${url}comments/`, "POST", { comment_html: html });
      setComment("");
      setFiles([]);
      setEditorKey((key) => key + 1);
      await refresh();
      setMessage(
        failed.length
          ? { kind: "error", text: `These files could not be attached: ${failed.join(", ")}.` }
          : { kind: "success", text: "Comment added." }
      );
    } catch (err) {
      setMessage({ kind: "error", text: (err as Error).message });
    } finally {
      setIsPosting(false);
    }
  };

  const handleAttach = async (picked: File[]) => {
    const { added, error: tooBig } = addFiles([], picked);
    setMessage(tooBig ? { kind: "error", text: tooBig } : null);
    if (added.length === 0) return;
    setIsAttaching(true);
    const failed = await uploadFiles(added);
    await refresh();
    setIsAttaching(false);
    if (tooBig) return;
    setMessage(
      failed.length
        ? { kind: "error", text: `These files could not be attached: ${failed.join(", ")}.` }
        : { kind: "success", text: "Files attached." }
    );
  };

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      {/* the page behind: clicking it closes the details */}
      <button type="button" aria-label="Close" className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={item ? `${item.key} ${item.name}` : "Work item"}
        className="relative flex h-full w-full max-w-[960px] flex-col border-l border-subtle bg-surface-1 shadow-raised-300"
      >
        <div className="flex h-12 shrink-0 items-center justify-between gap-3 px-5">
          <span className="flex min-w-0 items-center gap-2">
            <IconButton
              variant="ghost"
              size="sm"
              icon={<Icon icon={ArrowNarrowRightOutline} />}
              aria-label="Close details"
              onClick={onClose}
            />
            <span className="truncate text-caption-md-medium text-tertiary">{item?.project_name}</span>
          </span>
          <IconButton
            variant="ghost"
            size="sm"
            icon={<Icon icon={CloseOutline} />}
            aria-label="Close"
            onClick={onClose}
          />
        </div>

        {error ? (
          <p className="p-8 text-body-sm-regular text-tertiary">This work item is not available.</p>
        ) : !item ? (
          <div className="flex justify-center py-24">
            <LogoSpinner />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto px-8 pt-4 pb-10">
            {/* title */}
            <div className="flex items-center gap-1.5 text-caption-md-medium text-tertiary">
              {item.type && <span className="size-2.5 rounded-full" style={{ backgroundColor: item.type.color }} />}
              {item.key}
            </div>
            <h2 className="mt-1 text-h4-semibold break-words text-primary">{item.name}</h2>

            {item.type && (
              <div className="mt-3 rounded-md border border-subtle bg-layer-1 px-3 py-2">
                <p className="text-caption-sm-regular text-tertiary">Type</p>
                <p className="flex items-center gap-1.5 text-body-xs-medium text-primary">
                  <span className="size-2.5 rounded-full" style={{ backgroundColor: item.type.color }} />
                  {item.type.name}
                </p>
              </div>
            )}

            <section className="mt-6 flex flex-col gap-2">
              <h3 className="text-body-md-medium text-primary">Description</h3>
              {isEmptyHtml(item.description_html) ? (
                <None>No description.</None>
              ) : (
                <IntakeReadOnlyHtml id={`${editorId}-description`} html={item.description_html} base={base} />
              )}
            </section>

            {/* files */}
            <section className="mt-6 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-body-sm-medium text-primary">
                  Attachments{attachments.length ? ` (${attachments.length})` : ""}
                </h3>
                <FileDropZone
                  size="sm"
                  label={isAttaching ? "Uploading…" : "Attach files"}
                  disabled={isAttaching}
                  onFiles={(picked) => void handleAttach(picked)}
                />
              </div>
              <FileCards files={attachments} />
            </section>

            {/* properties: only the state can be changed */}
            <section className="mt-8 flex flex-col">
              <h3 className="pb-2 text-body-sm-medium text-primary">Properties</h3>
              <Property icon={<StateOutline className="size-3.5" />} label="State">
                {item.state && (
                  <div className="flex flex-col">
                    <div className="-ml-2 w-fit">
                      <StateSelect
                        getValues={async () => ({ results: stateOptions, next_page_results: false })}
                        value={stateOptions[0] ?? null}
                        onChange={(id) => void handleState(id)}
                        variant="select-ghost-md"
                        disabled={item.allowed_states.length === 0}
                        allowedStateIds={new Set(stateOptions.map((state) => state.id))}
                      />
                    </div>
                    {item.allowed_states.length === 0 && (
                      <span className="text-caption-sm-regular text-placeholder">
                        The workflow does not let you move it from here.
                      </span>
                    )}
                  </div>
                )}
              </Property>
              <Property icon={<MembersOutline className="size-3.5" />} label="Assignees">
                {item.assignees.length ? (
                  <span className="flex flex-wrap items-center gap-2">
                    {item.assignees.map((person) => (
                      <span key={person.id} className="flex items-center gap-1.5">
                        <Avatar name={person.name} className="size-5 text-[9px]" />
                        {person.name}
                      </span>
                    ))}
                  </span>
                ) : (
                  <None />
                )}
              </Property>
              <Property icon={<PriorityOutline className="size-3.5" />} label="Priority">
                <span className="flex items-center gap-1.5">
                  <PriorityIcon priority={item.priority} className="size-3.5" />
                  {PRIORITY_LABELS[item.priority] ?? "None"}
                </span>
              </Property>
              <Property icon={<CalendarOutline className="size-3.5" />} label="Start date">
                {item.start_date ? renderFormattedDate(item.start_date) : <None />}
              </Property>
              <Property icon={<CalendarOutline className="size-3.5" />} label="Due date">
                {item.target_date ? renderFormattedDate(item.target_date) : <None />}
              </Property>
              <Property icon={<ModuleOutline className="size-3.5" />} label="Modules">
                {item.modules.length ? item.modules.map((module) => module.name).join(", ") : <None>No module</None>}
              </Property>
              <Property icon={<CyclesOutline className="size-3.5" />} label="Sprint">
                {item.sprint ? item.sprint.name : <None>No sprint</None>}
              </Property>
              <Property icon={<LayerStackOutline className="size-3.5" />} label="Type">
                {item.type ? (
                  <span className="flex items-center gap-1.5">
                    <span className="size-2.5 rounded-full" style={{ backgroundColor: item.type.color }} />
                    {item.type.name}
                  </span>
                ) : (
                  <None />
                )}
              </Property>
              <Property icon={<ParentOutline className="size-3.5" />} label="Feature">
                {item.parent ? `${item.parent.key} ${item.parent.name}` : <None>No feature</None>}
              </Property>
              <Property icon={<MilestoneOutline className="size-3.5" />} label="Milestone">
                {item.milestone ? item.milestone.name : <None>No milestone</None>}
              </Property>
              <Property icon={<LabelsOutline className="size-3.5" />} label="Labels">
                {item.labels.length ? (
                  <span className="flex flex-wrap gap-1">
                    {item.labels.map((label) => (
                      <LabelChip key={label.id} label={label} />
                    ))}
                  </span>
                ) : (
                  <None />
                )}
              </Property>
              <Property icon={<UserOutline className="size-3.5" />} label="Created by">
                {item.created_by ? (
                  <span className="flex items-center gap-1.5">
                    <Avatar name={item.created_by.name} className="size-5 text-[9px]" />
                    {item.created_by.name}
                    {item.is_mine && <span className="text-tertiary">(you)</span>}
                  </span>
                ) : (
                  <None>—</None>
                )}
              </Property>
            </section>

            {/* activity: the comment box, then comments and history */}
            <section className="mt-8 flex flex-col gap-4">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <h3 className="text-h5-medium text-primary">Activity</h3>
                  <div className="flex gap-0.5 rounded-md border border-subtle p-0.5" role="tablist">
                    {(
                      [
                        ["all", "All"],
                        ["comments", "Comments"],
                        ["history", "History"],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        role="tab"
                        aria-selected={tab === key}
                        onClick={() => setTab(key)}
                        className={cn(
                          "rounded-sm px-2.5 py-1 text-body-xs-medium",
                          tab === key ? "bg-accent-subtle text-accent-primary" : "text-secondary hover:text-primary"
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <IconButton
                  variant="ghost"
                  size="sm"
                  icon={<Icon icon={newestFirst ? SortDescendingOutline : SortAscendingOutline} />}
                  aria-label={newestFirst ? "Newest first" : "Oldest first"}
                  onClick={() => setNewestFirst((current) => !current)}
                />
              </div>

              {tab !== "history" && (
                <div className="rounded-md border border-subtle p-2">
                  <IntakeCommentEditor
                    key={editorKey}
                    id={`${editorId}-new-comment`}
                    base={base}
                    uploadUrl={`${url}comment-images/`}
                    onChange={setComment}
                    onSubmit={() => void handleComment()}
                    isEmpty={isEmptyHtml(comment) && files.length === 0}
                    isSubmitting={isPosting}
                  >
                    <FileCards
                      files={commentPreviews}
                      className="sm:grid-cols-3 lg:grid-cols-3"
                      onRemove={(key) =>
                        setFiles((current) => current.filter((_, index) => commentPreviews[index]?.key !== key))
                      }
                    />
                    <div>
                      <FileDropZone size="sm" disabled={isPosting} onFiles={pickForComment} />
                    </div>
                  </IntakeCommentEditor>
                </div>
              )}
              {message && (
                <p
                  className={cn(
                    "text-body-xs-regular",
                    message.kind === "error" ? "text-danger-primary" : "text-success-primary"
                  )}
                >
                  {message.text}
                </p>
              )}

              {activity.length === 0 && <None>Nothing yet.</None>}
              <ol className="flex flex-col gap-5">
                {activity.map((entry) =>
                  entry.kind === "comment" ? (
                    <li key={`c-${entry.id}`} className="flex gap-3">
                      <Avatar name={entry.author} />
                      <div className="min-w-0 flex-1">
                        <p className="text-body-xs-medium text-primary">
                          {entry.author}
                          {entry.is_mine && <span className="font-normal text-tertiary"> (you)</span>}
                        </p>
                        <p className="text-caption-sm-regular text-tertiary">{activityDate(entry.created_at)}</p>
                        <div className="mt-1.5 rounded-md border border-subtle px-3 py-2">
                          <IntakeReadOnlyHtml
                            id={`${editorId}-comment-${entry.id}`}
                            html={entry.comment_html}
                            base={base}
                          />
                        </div>
                      </div>
                    </li>
                  ) : (
                    <li key={`h-${entry.id}`} className="flex gap-3">
                      <Avatar name={entry.actor} />
                      <div className="min-w-0 flex-1">
                        <p className="text-body-xs-regular text-secondary">
                          <span className="font-medium text-primary">{entry.actor}</span> {historyLabel(entry)}
                        </p>
                        <p className="text-caption-sm-regular text-tertiary">{activityDate(entry.created_at)}</p>
                        {entry.field === "state" && (
                          <span className="mt-1.5 flex flex-wrap items-center gap-2">
                            <StateChip name={entry.old_value} state={stateByName.get(entry.old_value ?? "")} />
                            <ArrowNarrowRightOutline className="size-3.5 text-tertiary" />
                            <StateChip name={entry.new_value} state={stateByName.get(entry.new_value ?? "")} />
                          </span>
                        )}
                        {(entry.field === "assignees" || entry.field === "labels" || entry.field === "priority") &&
                          (entry.new_value || entry.old_value) && (
                            <p className="mt-1 text-body-xs-regular text-primary">
                              {entry.new_value || entry.old_value}
                            </p>
                          )}
                      </div>
                    </li>
                  )
                )}
              </ol>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
