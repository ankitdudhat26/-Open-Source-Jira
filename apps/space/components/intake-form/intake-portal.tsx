/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { AttachOutline, CloseOutline, SearchOutline } from "@makeplane/propel/icons";
import { API_BASE_URL, SPACE_BASE_PATH } from "@plane/constants";
import type { EditorRefApi } from "@plane/editor";
import { HlinkLockup, PriorityIcon } from "@plane/blocks/icons";
import { Select } from "@plane/blocks/select";
import { AuthService } from "@plane/services";
import type { TIssuePriorities } from "@plane/types";
import { cn, renderFormattedDate } from "@plane/utils";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
// local imports
import { IntakeDescriptionEditor } from "./description-editor";
import { ThemeSwitch } from "./theme-switch";

type TFieldKey = "title" | "description" | "type" | "priority" | "labels" | "attachments";

type TOption = { id: string; name: string; color?: string };

type TProjectForm = {
  project_id: string;
  project_name: string;
  fields: TFieldKey[];
  types: { id: string; name: string; color: string }[];
  priorities: { value: string; label: string }[];
  labels: { id: string; name: string; color: string }[];
};

type TPortal = {
  access: "login" | "not_invited" | "ok";
  project_name: string;
  workspace_name: string;
  email?: string;
  forms?: TProjectForm[];
};

type TRequest = {
  id: string;
  issue_id: string;
  project_name: string;
  key: string;
  name: string;
  priority: TIssuePriorities;
  type: { name: string; color: string } | null;
  labels: { name: string; color: string }[];
  status: number;
  status_label: string;
  decline_reason: string;
  duplicate_of: string | null;
  snoozed_till: string | null;
  created_at: string;
};

type TDraft = { title: string; description: string; typeId: string; priority: string; labelIds: string[] };

const EMPTY_DRAFT: TDraft = { title: "", description: "", typeId: "", priority: "", labelIds: [] };
const MAX_FILE_SIZE = 5 * 1024 * 1024;
const authService = new AuthService();

// -2 pending, -1 declined, 0 snoozed, 1 accepted, 2 duplicate
const STATUS_STYLES: Record<number, string> = {
  [-2]: "bg-warning-subtle text-warning-primary",
  [-1]: "bg-danger-subtle text-danger-primary",
  0: "bg-layer-3 text-secondary",
  1: "bg-success-subtle text-success-primary",
  2: "bg-layer-3 text-secondary",
};
const STATUS_FILTERS = [
  { key: "all", label: "All", statuses: null },
  { key: "pending", label: "Pending", statuses: [-2, 0] },
  { key: "accepted", label: "Accepted", statuses: [1] },
  { key: "declined", label: "Declined", statuses: [-1] },
  { key: "duplicate", label: "Duplicate", statuses: [2] },
] as const;
type TStatusFilter = (typeof STATUS_FILTERS)[number]["key"];
const PRIORITY_LABELS: Record<string, string> = {
  urgent: "Urgent",
  high: "High",
  medium: "Medium",
  low: "Low",
  none: "None",
};

const getJson = async <T,>(url: string): Promise<T> => {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as T;
};

/** Whether the editor's HTML has no text (an empty paragraph, line breaks…). */
const isEmptyHtml = (html: string) =>
  !html ||
  (!/<(img|table|hr|pre|ul|ol)\b/i.test(html) &&
    !html
      .replace(/<[^>]*>/g, "")
      .replace(/&nbsp;/g, " ")
      .trim());

function ColorDot({ color }: { color?: string }) {
  return (
    <span className="inline-block size-2.5 shrink-0 rounded-full" style={{ backgroundColor: color || "#6B7280" }} />
  );
}

function FieldLabel({ children, required, htmlFor }: { children: string; required?: boolean; htmlFor?: string }) {
  const content = (
    <>
      {children}
      {required && <span className="text-danger-primary"> *</span>}
    </>
  );
  return htmlFor ? (
    <label htmlFor={htmlFor} className="text-body-xs-medium text-primary">
      {content}
    </label>
  ) : (
    <span className="text-body-xs-medium text-primary">{content}</span>
  );
}

type TOptionSelectProps = {
  options: TOption[];
  placeholder: string;
  icon?: (option: TOption) => React.ReactNode;
} & (
  | { multiple?: false; value: string; onChange: (id: string) => void }
  | {
      multiple: true;
      value: string[];
      onChange: (ids: string[]) => void;
    }
);

/** A field-style dropdown whose options (and selected value) carry an icon: type colour, priority, label colour. */
function OptionSelect(props: TOptionSelectProps) {
  const { options, placeholder, icon } = props;
  const byId = new Map(options.map((option) => [option.id, option]));
  const common = {
    getValues: () => options,
    getOptionValue: (option: TOption) => option.id,
    getOptionLabel: (option: TOption) => option.name,
    getOptionIcon: icon,
    placeholder,
    showSearch: options.length > 8,
    pinSelected: false,
  };
  const trigger = (
    // the select chrome's border width is dropped from its class list in this app — set it here
    <Select.Trigger<TOption> variant="select-lg" className="border">
      {(selected) => (
        <span className="flex min-w-0 grow items-center gap-1.5 text-left">
          {selected.length === 0 ? (
            <span className="truncate text-placeholder">{placeholder}</span>
          ) : selected.length === 1 ? (
            <>
              {icon?.(selected[0])}
              <span className="truncate">{selected[0].name}</span>
            </>
          ) : (
            <>
              <span className="flex shrink-0 items-center -space-x-0.5">
                {selected.slice(0, 4).map((option) => (
                  <span key={option.id} className="ring-layer-2 flex rounded-full ring-2">
                    {icon?.(option)}
                  </span>
                ))}
              </span>
              <span className="truncate">{selected.map((option) => option.name).join(", ")}</span>
            </>
          )}
        </span>
      )}
    </Select.Trigger>
  );
  if (props.multiple)
    return (
      <Select<TOption>
        {...common}
        multiple
        value={props.value.flatMap((id) => byId.get(id) ?? [])}
        onChange={props.onChange}
      >
        {trigger}
      </Select>
    );
  return (
    <Select<TOption> {...common} value={byId.get(props.value) ?? null} onChange={props.onChange}>
      {trigger}
    </Select>
  );
}

function SignOutButton({ anchor }: { anchor: string }) {
  const [csrfToken, setCsrfToken] = useState<string>();
  useEffect(() => {
    authService
      .requestCSRFToken()
      .then((data) => data?.csrf_token && setCsrfToken(data.csrf_token))
      .catch(() => {});
  }, []);
  return (
    <form method="POST" action={`${API_BASE_URL}/auth/spaces/sign-out/`}>
      <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken ?? ""} />
      <input type="hidden" name="next_path" value={`/intake/${anchor}`} />
      <Button type="submit" variant="secondary" size="md" stretch="auto" label="Log out" disabled={!csrfToken} />
    </form>
  );
}

type TRequestFormProps = {
  anchor: string;
  forms: TProjectForm[];
  onSent: () => void;
};

function RequestForm({ anchor, forms, onSent }: TRequestFormProps) {
  const [projectId, setProjectId] = useState(forms[0]?.project_id ?? "");
  const [draft, setDraft] = useState<TDraft>(EMPTY_DRAFT);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSending, setIsSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const descriptionRef = useRef<EditorRefApi>(null);
  // a new key gives an empty editor after a request is sent
  const [editorKey, setEditorKey] = useState(0);
  const ids = { title: useId(), description: useId() };

  const form = forms.find((item) => item.project_id === projectId) ?? forms[0];
  const shows = (key: TFieldKey) => !!form?.fields.includes(key);
  const projectOptions = forms.map((item) => ({ id: item.project_id, name: item.project_name }));
  const typeOptions = form?.types ?? [];
  const priorityOptions = (form?.priorities ?? []).map((item) => ({ id: item.value, name: item.label }));
  const labelOptions = form?.labels ?? [];
  const hasDetails =
    forms.length > 1 ||
    (shows("type") && typeOptions.length > 0) ||
    shows("priority") ||
    (shows("labels") && labelOptions.length > 0);

  const handleFiles = (list: FileList | null) => {
    const chosen = Array.from(list ?? []);
    const tooBig = chosen.filter((file) => file.size > MAX_FILE_SIZE);
    setError(tooBig.length ? `${tooBig.map((file) => file.name).join(", ")} is over 5 MB.` : "");
    setFiles((current) => [...current, ...chosen.filter((file) => file.size <= MAX_FILE_SIZE)]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form) return;
    const title = draft.title.trim();
    if (!title) {
      setError("Title is required.");
      return;
    }
    setIsSending(true);
    setError("");
    setNotice("");
    try {
      const issue: Record<string, unknown> = { name: title };
      if (shows("description") && !isEmptyHtml(draft.description)) issue.description_html = draft.description;
      if (shows("type") && draft.typeId) issue.type_id = draft.typeId;
      if (shows("priority") && draft.priority) issue.priority = draft.priority;
      if (shows("labels") && draft.labelIds.length) issue.label_ids = draft.labelIds;
      const response = await fetch(`${API_BASE_URL}/api/public/intake-forms/${anchor}/requests/`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: form.project_id, issue }),
      });
      const data = (await response.json().catch(() => ({}))) as { issue_id?: string; error?: string };
      if (!response.ok || !data.issue_id) {
        setError(data.error ?? "Your request could not be sent. Try again.");
        return;
      }
      const uploads = shows("attachments")
        ? await Promise.all(
            files.map(async (file) => {
              const body = new FormData();
              body.append("file", file);
              const upload = await fetch(
                `${API_BASE_URL}/api/public/intake-forms/${anchor}/requests/${data.issue_id}/attachments/`,
                { method: "POST", credentials: "include", body }
              ).catch(() => undefined);
              return upload?.ok ? undefined : file.name;
            })
          )
        : [];
      const failed = uploads.filter((name): name is string => !!name);
      setDraft(EMPTY_DRAFT);
      setEditorKey((key) => key + 1);
      setFiles([]);
      setNotice(
        failed.length
          ? `Your request was sent, but these files could not be attached: ${failed.join(", ")}.`
          : `Your request was sent to ${form.project_name}. You can follow it under My requests.`
      );
      onSent();
    } catch {
      setError("Your request could not be sent. Check your connection and try again.");
    } finally {
      setIsSending(false);
    }
  };

  if (!form) return null;

  return (
    <form
      className="flex flex-col gap-6 rounded-lg border border-subtle bg-surface-1 p-5 sm:p-8"
      onSubmit={handleSubmit}
      noValidate
    >
      <div className="flex flex-col gap-1.5">
        <FieldLabel htmlFor={ids.title} required>
          Title
        </FieldLabel>
        <InputGroup size="lg">
          <Input
            id={ids.title}
            size="lg"
            value={draft.title}
            maxLength={255}
            placeholder="A short summary of what you need"
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
          />
        </InputGroup>
      </div>

      {shows("description") && (
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Description</FieldLabel>
          <IntakeDescriptionEditor
            key={editorKey}
            ref={descriptionRef}
            id={ids.description}
            onChange={(html) => setDraft((current) => ({ ...current, description: html }))}
          />
        </div>
      )}

      {hasDetails && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {forms.length > 1 && (
            <div className="flex flex-col gap-1.5">
              <FieldLabel required>Project</FieldLabel>
              <OptionSelect
                options={projectOptions}
                placeholder="Choose the project"
                value={form.project_id}
                onChange={(value) => {
                  setProjectId(value);
                  // types and labels belong to the project
                  setDraft((current) => ({ ...current, typeId: "", labelIds: [] }));
                }}
              />
            </div>
          )}
          {shows("type") && typeOptions.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <FieldLabel>Type</FieldLabel>
              <OptionSelect
                options={typeOptions}
                placeholder="Choose a type"
                icon={(option) => <ColorDot color={option.color} />}
                value={draft.typeId}
                onChange={(value) => setDraft((current) => ({ ...current, typeId: value }))}
              />
            </div>
          )}
          {shows("priority") && (
            <div className="flex flex-col gap-1.5">
              <FieldLabel>Priority</FieldLabel>
              <OptionSelect
                options={priorityOptions}
                placeholder="Choose a priority"
                icon={(option) => <PriorityIcon priority={option.id as TIssuePriorities} className="size-3.5" />}
                value={draft.priority}
                onChange={(value) => setDraft((current) => ({ ...current, priority: value }))}
              />
            </div>
          )}
          {shows("labels") && labelOptions.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <FieldLabel>Labels</FieldLabel>
              <OptionSelect
                multiple
                options={labelOptions}
                placeholder="Choose labels"
                icon={(option) => <ColorDot color={option.color} />}
                value={draft.labelIds}
                onChange={(values) => setDraft((current) => ({ ...current, labelIds: values }))}
              />
            </div>
          )}
        </div>
      )}

      {shows("attachments") && (
        <div className="flex flex-col gap-2">
          <FieldLabel>Attachments</FieldLabel>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            aria-label="Attachments"
            onChange={(event) => handleFiles(event.target.files)}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex flex-col items-center gap-1 rounded-md border border-dashed border-subtle-1 bg-layer-1 px-4 py-5 text-center hover:bg-layer-1-hover"
          >
            <AttachOutline className="size-5 text-tertiary" />
            <span className="text-body-xs-medium text-primary">Add files</span>
            <span className="text-caption-sm-regular text-tertiary">
              Documents, screenshots and other files, up to 5 MB each
            </span>
          </button>
          {files.length > 0 && (
            <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
              {files.map((file) => (
                <li
                  key={`${file.name}-${file.size}-${file.lastModified}`}
                  className="flex items-center gap-2 px-3 py-1.5"
                >
                  <AttachOutline className="size-4 shrink-0 text-tertiary" />
                  <span className="min-w-0 flex-1 truncate text-body-xs-regular text-primary">{file.name}</span>
                  <span className="text-caption-sm-regular text-tertiary">
                    {Math.max(1, Math.round(file.size / 1024))} KB
                  </span>
                  <IconButton
                    variant="ghost"
                    size="xs"
                    icon={<Icon icon={CloseOutline} />}
                    aria-label={`Remove ${file.name}`}
                    onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="flex flex-col-reverse items-stretch gap-3 border-t border-subtle pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          {error && <p className="text-body-xs-regular text-danger-primary">{error}</p>}
          {notice && <p className="text-body-xs-regular text-success-primary">{notice}</p>}
        </div>
        <Button
          type="submit"
          variant="primary"
          size="lg"
          stretch="auto"
          label={isSending ? "Sending..." : "Send request"}
          disabled={isSending}
        />
      </div>
    </form>
  );
}

function StatusNote({ request }: { request: TRequest }) {
  if (request.status === -1)
    return (
      <span className="whitespace-pre-line text-primary">
        <span className="font-medium text-danger-primary">Reason: </span>
        {request.decline_reason || "No reason given."}
      </span>
    );
  if (request.status === 1) return <span>Accepted — the team is working on it.</span>;
  if (request.status === 2 && request.duplicate_of) return <span>Same as {request.duplicate_of}.</span>;
  if (request.status === 0 && request.snoozed_till)
    return <span>On hold until {renderFormattedDate(request.snoozed_till)}.</span>;
  return <span>Waiting for review.</span>;
}

function RequestList({ requests, showProject }: { requests: TRequest[]; showProject: boolean }) {
  const [filter, setFilter] = useState<TStatusFilter>("all");
  const [search, setSearch] = useState("");

  const counts = useMemo(
    () =>
      Object.fromEntries(
        STATUS_FILTERS.map((item) => [
          item.key,
          item.statuses
            ? requests.filter((request) => (item.statuses as readonly number[]).includes(request.status)).length
            : requests.length,
        ])
      ) as Record<TStatusFilter, number>,
    [requests]
  );
  const statuses = STATUS_FILTERS.find((item) => item.key === filter)?.statuses ?? null;
  const query = search.trim().toLowerCase();
  const visible = requests.filter(
    (request) =>
      (!statuses || (statuses as readonly number[]).includes(request.status)) &&
      (!query || `${request.key} ${request.name}`.toLowerCase().includes(query))
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by status">
          {STATUS_FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={filter === item.key}
              onClick={() => setFilter(item.key)}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-body-xs-medium",
                filter === item.key
                  ? "border-accent-strong bg-accent-subtle text-accent-primary"
                  : "border-subtle bg-surface-1 text-secondary hover:bg-layer-1-hover"
              )}
            >
              {item.label}
              <span
                className={cn(
                  "rounded-sm px-1.5 text-caption-sm-medium",
                  filter === item.key ? "bg-accent-primary text-on-color" : "bg-layer-3 text-tertiary"
                )}
              >
                {counts[item.key]}
              </span>
            </button>
          ))}
        </div>
        <div className="w-full sm:w-72">
          <InputGroup size="md">
            <Icon icon={SearchOutline} />
            <Input
              size="md"
              value={search}
              placeholder="Search requests"
              aria-label="Search requests"
              onChange={(event) => setSearch(event.target.value)}
            />
          </InputGroup>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-subtle bg-surface-1">
        {visible.length === 0 ? (
          <p className="px-5 py-14 text-center text-body-xs-regular text-tertiary">
            {requests.length === 0
              ? "No requests yet. Use New request to send your first one."
              : "No requests match this filter."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left">
              <thead className="border-b border-subtle bg-layer-1 text-caption-sm-medium text-tertiary">
                <tr>
                  <th className="w-28 px-4 py-2.5 font-medium">ID</th>
                  <th className="px-4 py-2.5 font-medium">Request</th>
                  {showProject && <th className="w-44 px-4 py-2.5 font-medium">Project</th>}
                  <th className="w-28 px-4 py-2.5 font-medium">Type</th>
                  <th className="w-28 px-4 py-2.5 font-medium">Priority</th>
                  <th className="w-28 px-4 py-2.5 font-medium">Status</th>
                  <th className="w-[28%] px-4 py-2.5 font-medium">Note</th>
                  <th className="w-28 px-4 py-2.5 font-medium">Sent</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-subtle">
                {visible.map((request) => (
                  <tr key={request.id} className="align-top">
                    <td className="px-4 py-3 text-caption-md-medium whitespace-nowrap text-tertiary">{request.key}</td>
                    <td className="px-4 py-3">
                      <p className="text-body-xs-medium break-words text-primary">{request.name}</p>
                      {request.labels.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {request.labels.map((label) => (
                            <span
                              key={label.name}
                              className="flex items-center gap-1 rounded-sm border border-subtle px-1.5 py-0.5 text-caption-sm-regular text-secondary"
                            >
                              <ColorDot color={label.color} />
                              {label.name}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    {showProject && (
                      <td className="px-4 py-3 text-body-xs-regular text-secondary">{request.project_name}</td>
                    )}
                    <td className="px-4 py-3 text-body-xs-regular text-secondary">
                      {request.type ? (
                        <span className="flex items-center gap-1.5">
                          <ColorDot color={request.type.color} />
                          {request.type.name}
                        </span>
                      ) : (
                        <span className="text-placeholder">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-body-xs-regular text-secondary">
                      <span className="flex items-center gap-1.5">
                        <PriorityIcon priority={request.priority} className="size-3.5" />
                        {PRIORITY_LABELS[request.priority] ?? "None"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "inline-flex rounded-sm px-1.5 py-0.5 text-caption-sm-medium whitespace-nowrap",
                          STATUS_STYLES[request.status] ?? "bg-layer-3 text-secondary"
                        )}
                      >
                        {request.status_label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-body-xs-regular text-tertiary">
                      <StatusNote request={request} />
                    </td>
                    <td className="px-4 py-3 text-body-xs-regular whitespace-nowrap text-tertiary">
                      {renderFormattedDate(request.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Message({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-3 rounded-lg border border-subtle bg-surface-1 px-6 py-12 text-center">
      <h1 className="text-h4-semibold text-primary">{title}</h1>
      {children}
    </div>
  );
}

/**
 * The page behind a project's Intake link. Invited clients log in here, send requests with the form the project set
 * up (choosing the project when they are invited to more than one) and follow each request: pending, accepted, or
 * declined with the reason. They see nothing else of the project.
 */
export function IntakePortal({ anchor }: { anchor: string }) {
  const [tab, setTab] = useState<"new" | "requests">("new");
  const base = `${API_BASE_URL}/api/public/intake-forms/${anchor}/`;
  const {
    data: portal,
    error,
    isLoading,
  } = useSWR(anchor ? base : null, (url: string) => getJson<TPortal>(url), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  const { data: requests, mutate: mutateRequests } = useSWR(
    portal?.access === "ok" ? `${base}requests/` : null,
    (url: string) => getJson<TRequest[]>(url),
    { revalidateOnFocus: true }
  );

  let content: React.ReactNode;
  if (isLoading) {
    content = (
      <div className="flex justify-center py-24">
        <LogoSpinner />
      </div>
    );
  } else if (error || !portal) {
    content = (
      <Message title="This form is not available">
        <p className="text-body-sm-regular text-tertiary">
          The link may have been turned off or replaced. Ask the person who shared it for a new link.
        </p>
      </Message>
    );
  } else if (portal.access === "login") {
    content = (
      <Message title={`Send a request to ${portal.project_name}`}>
        <p className="text-body-sm-regular text-tertiary">
          Log in with the email address you were invited with to send requests and follow them.
        </p>
        <Button
          variant="primary"
          size="lg"
          stretch="auto"
          label="Log in"
          // a full page load: the sign-in page starts its own session check
          onClick={() => window.location.assign(`${SPACE_BASE_PATH}/?next_path=/intake/${anchor}`)}
        />
      </Message>
    );
  } else if (portal.access === "not_invited") {
    content = (
      <Message title="You are not invited to this form">
        <p className="text-body-sm-regular text-tertiary">
          You are logged in as <span className="font-medium text-primary">{portal.email}</span>. Ask the{" "}
          {portal.project_name} team to invite this email, or log out and log in with the email you were invited with.
        </p>
        <SignOutButton anchor={anchor} />
      </Message>
    );
  } else {
    const forms = portal.forms ?? [];
    content = (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-h3-semibold text-primary">
            {forms.length > 1 ? "Requests" : `Requests to ${portal.project_name}`}
          </h1>
          <p className="text-body-sm-regular text-tertiary">
            Send a request to the team and follow what happens to it. A declined request shows the reason.
          </p>
        </div>
        <div className="flex gap-1 border-b border-subtle" role="tablist">
          {(
            [
              ["new", "New request"],
              ["requests", `My requests${requests ? ` (${requests.length})` : ""}`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={cn(
                "-mb-px border-b-2 px-4 py-2.5 text-body-sm-medium",
                tab === key ? "border-accent-strong text-accent-primary" : "border-transparent text-tertiary"
              )}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "new" ? (
          <RequestForm anchor={anchor} forms={forms} onSent={() => void mutateRequests()} />
        ) : requests ? (
          <RequestList requests={requests} showProject={forms.length > 1} />
        ) : (
          <div className="flex justify-center py-16">
            <LogoSpinner />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen w-full flex-col bg-surface-2">
      <header className="sticky top-0 z-10 flex h-14 w-full shrink-0 items-center justify-between gap-4 border-b border-subtle bg-surface-1 px-4 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <HlinkLockup className="h-6 w-auto shrink-0 text-primary" />
          {portal && (
            <>
              <span className="h-5 w-px shrink-0 bg-layer-3" />
              <span className="truncate text-body-xs-medium text-secondary">
                {portal.workspace_name} · {portal.project_name}
              </span>
            </>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <ThemeSwitch />
          {portal?.access === "ok" && (
            <>
              <span className="h-5 w-px shrink-0 bg-layer-3" />
              <span className="hidden text-body-xs-regular text-tertiary sm:inline">{portal.email}</span>
              <SignOutButton anchor={anchor} />
            </>
          )}
        </div>
      </header>
      <main className="w-full flex-1 px-4 py-6 sm:px-8 sm:py-8">{content}</main>
    </div>
  );
}
