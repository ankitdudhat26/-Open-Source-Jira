/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { cn, renderFormattedDate } from "@plane/utils";
// services
import type { TJiraSyncOptions, TJiraSyncRun } from "@/services/jira-import.service";
import { jiraImportService } from "@/services/jira-import.service";

type Props = { workspaceSlug: string };

const errorMessage = (error: unknown, fallback: string) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string" ? error.error : fallback;

const STAT_LABELS: Record<string, string> = {
  projects_created: "projects created",
  issues_created: "work items created",
  issues_updated: "work items updated",
  issues_unchanged: "unchanged",
  statuses_created: "statuses",
  sprints_created: "sprints",
  modules_created: "modules",
  comments_created: "comments",
  comments_updated: "comments updated",
  history_entries: "history entries",
  attachments_copied: "attachments",
  links_created: "links",
  users_created: "accounts created",
  users_added: "added to the workspace",
  users_existing: "already here",
  users_without_email: "without a visible email",
  project_members_added: "project members added",
  project_roles_updated: "project roles updated",
};

const PAGE_SIZES = [25, 50, 100];

type TProjectFilter = "all" | "new" | "imported";

const CONTROL = "rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary";

const STATUS_STYLE: Record<TJiraSyncRun["status"], string> = {
  queued: "bg-layer-3 text-secondary",
  running: "bg-accent-subtle text-accent-primary",
  completed: "bg-success-subtle text-success-primary",
  failed: "bg-danger-subtle text-danger-primary",
};

const formatDateTime = (value: string | null) =>
  value
    ? `${renderFormattedDate(value)} ${new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : "—";

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-subtle p-4">
      <h3 className="text-body-sm-medium text-primary">{title}</h3>
      {description && <p className="mt-1 text-caption-md-regular text-tertiary">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function RunCard({ run, workspaceSlug }: { run: TJiraSyncRun; workspaceSlug: string }) {
  const [open, setOpen] = useState(run.status === "running");
  const stats = Object.entries(STAT_LABELS)
    .filter(([key]) => run.stats?.[key])
    .map(([key, label]) => `${run.stats[key]} ${label}`);
  return (
    <div className="rounded-md border border-subtle px-3 py-2.5">
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-2 text-left"
        onClick={() => setOpen(!open)}
      >
        <span className={cn("rounded-sm px-1.5 py-0.5 text-caption-sm-medium capitalize", STATUS_STYLE[run.status])}>
          {run.status}
        </span>
        <span className="text-body-xs-medium text-primary">
          {run.options?.kind === "users" ? "Jira users" : run.project_keys.join(", ")}
        </span>
        <span className="text-caption-md-regular text-tertiary">{formatDateTime(run.created_at)}</span>
        {run.status === "running" && (
          <span className="ml-auto text-caption-md-regular text-accent-primary">{run.current_step || "Starting"}…</span>
        )}
      </button>
      {open && (
        <div className="mt-2 space-y-2 text-caption-md-regular text-secondary">
          {stats.length > 0 && <p>{stats.join(" · ")}</p>}
          {Object.entries(run.projects ?? {}).length > 0 && (
            <p>
              Projects:{" "}
              {Object.entries(run.projects).map(([key, project], index) => (
                <span key={key}>
                  {index > 0 && ", "}
                  <Link
                    className="text-accent-primary hover:underline"
                    href={`/${workspaceSlug}/projects/${project.project_id}/issues`}
                  >
                    {key} → {project.name}
                  </Link>
                </span>
              ))}
            </p>
          )}
          {run.error && <p className="text-danger-primary">Error: {run.error}</p>}
          {run.unmatched_users?.length > 0 && (
            <div>
              <p className="text-primary">
                People in Jira without an account here ({run.unmatched_users.length}). Invite them and sync again to
                assign their work items to them:
              </p>
              <p className="text-tertiary">{run.unmatched_users.map((user) => user.email || user.name).join(", ")}</p>
            </div>
          )}
          {run.warnings?.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-warning-primary">
              {run.warnings.slice(0, 20).map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <p className="text-tertiary">
            Started {formatDateTime(run.started_at)} · Finished {formatDateTime(run.finished_at)}
          </p>
        </div>
      )}
    </div>
  );
}

/** Settings → Jira import: connect Jira (read only), pick projects and sync them; every run is listed. */
export const JiraImportRoot = observer(function JiraImportRoot(props: Props) {
  const { workspaceSlug } = props;
  const { data: connection, mutate: refreshConnection } = useSWR(`JIRA_CONNECTION_${workspaceSlug}`, () =>
    jiraImportService.getConnection(workspaceSlug)
  );
  const isConnected = !!connection?.connected;
  const {
    data: projects,
    error: projectsError,
    isLoading: projectsLoading,
    mutate: refreshProjects,
  } = useSWR(
    isConnected ? `JIRA_PROJECTS_${workspaceSlug}` : null,
    () => jiraImportService.getProjects(workspaceSlug),
    {
      revalidateOnFocus: false,
    }
  );
  const { data: runs, mutate: refreshRuns } = useSWR(`JIRA_RUNS_${workspaceSlug}`, () =>
    jiraImportService.getRuns(workspaceSlug)
  );
  const isRunning = !!runs?.some((run) => run.status === "queued" || run.status === "running");

  // follow a running sync
  useEffect(() => {
    if (!isRunning) return;
    const timer = window.setInterval(() => void refreshRuns(), 3000);
    return () => window.clearInterval(timer);
  }, [isRunning, refreshRuns]);
  const latestStatus = runs?.[0]?.status;
  useEffect(() => {
    if (latestStatus === "completed") void refreshProjects();
  }, [latestStatus, refreshProjects]);

  const [form, setForm] = useState({ site_url: "", email: "", api_token: "" });
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [options, setOptions] = useState<Required<Omit<TJiraSyncOptions, "kind">>>({
    comments: true,
    history: true,
    attachments: true,
    full: false,
  });
  const [starting, setStarting] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<TProjectFilter>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);

  useEffect(() => {
    if (connection?.connected)
      setForm((current) => ({ ...current, site_url: connection.site_url, email: connection.email }));
  }, [connection]);

  const allKeys = useMemo(() => (projects ?? []).map((project) => project.key), [projects]);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (projects ?? []).filter((project) => {
      if (filter === "new" && project.linked_project) return false;
      if (filter === "imported" && !project.linked_project) return false;
      if (!query) return true;
      return [project.key, project.name, project.lead ?? "", project.linked_project?.name ?? ""].some((text) =>
        text.toLowerCase().includes(query)
      );
    });
  }, [projects, search, filter]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageItems = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const filteredKeys = filtered.map((project) => project.key);
  const allFilteredSelected = filteredKeys.length > 0 && filteredKeys.every((key) => selected.has(key));

  const saveConnection = async () => {
    setSaving(true);
    try {
      await jiraImportService.saveConnection(workspaceSlug, form);
      await refreshConnection();
      void refreshProjects();
      setEditing(false);
      setForm((current) => ({ ...current, api_token: "" }));
      setToast({
        type: "success",
        title: "Jira connected",
        message: "Credentials checked. Jira is only read, never changed.",
      });
    } catch (error) {
      setToast({
        type: "error",
        title: "Could not connect",
        message: errorMessage(error, "Check the site, email and API token."),
      });
    } finally {
      setSaving(false);
    }
  };

  const startSync = async (keys: string[]) => {
    setStarting(true);
    try {
      await jiraImportService.startSync(workspaceSlug, keys, options);
      await refreshRuns();
      setToast({
        type: "success",
        title: "Sync started",
        message: `${keys.join(", ")} will be imported in the background.`,
      });
    } catch (error) {
      setToast({ type: "error", title: "Sync not started", message: errorMessage(error, "Please try again.") });
    } finally {
      setStarting(false);
    }
  };

  const startUserSync = async () => {
    setStarting(true);
    try {
      await jiraImportService.startUserSync(workspaceSlug);
      await refreshRuns();
      setToast({
        type: "success",
        title: "User sync started",
        message: "Active Jira users are being added in the background.",
      });
    } catch (error) {
      setToast({ type: "error", title: "User sync not started", message: errorMessage(error, "Please try again.") });
    } finally {
      setStarting(false);
    }
  };

  const selectFiltered = (checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      for (const key of filteredKeys) {
        if (checked) next.add(key);
        else next.delete(key);
      }
      return next;
    });

  const toggle = (key: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  if (!connection) return <p className="text-body-xs-regular text-tertiary">Loading…</p>;

  return (
    <div className="space-y-5">
      <Section
        title="1. Connect Jira"
        description="Use a Jira Cloud account that can see the projects. Create an API token at id.atlassian.com → Security → API tokens. The token is stored encrypted and Jira is only ever read: nothing in Jira is created, changed or deleted."
      >
        {isConnected && !editing ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-body-xs-regular text-secondary">
              Connected to <span className="font-medium text-primary">{connection.site_url}</span> as{" "}
              <span className="font-medium text-primary">{connection.account_name || connection.email}</span>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" stretch="auto" label="Change" onClick={() => setEditing(true)} />
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                label="Disconnect"
                onClick={() => setConfirmDisconnect(true)}
              />
            </div>
          </div>
        ) : (
          <form
            className="grid grid-cols-1 gap-3 md:grid-cols-3"
            onSubmit={(event) => {
              event.preventDefault();
              void saveConnection();
            }}
          >
            {(
              [
                ["site_url", "Jira site", "https://your-team.atlassian.net", "url"],
                ["email", "Account email", "you@company.com", "email"],
                ["api_token", isConnected ? "API token (leave empty to keep)" : "API token", "••••••••", "password"],
              ] as const
            ).map(([key, label, placeholder, type]) => (
              <label key={key} className="space-y-1 text-caption-md-medium text-secondary">
                <span>{label}</span>
                <InputGroup size="md">
                  <Input
                    size="md"
                    type={type}
                    value={form[key]}
                    onChange={(event) => setForm({ ...form, [key]: event.target.value })}
                    placeholder={placeholder}
                    autoComplete={key === "api_token" ? "new-password" : "off"}
                  />
                </InputGroup>
              </label>
            ))}
            <div className="flex gap-2 md:col-span-3">
              <Button
                variant="primary"
                size="sm"
                stretch="auto"
                type="submit"
                label={saving ? "Checking…" : "Save and test"}
                disabled={saving || !form.site_url || !form.email || (!isConnected && !form.api_token)}
              />
              {editing && (
                <Button variant="secondary" size="sm" stretch="auto" label="Cancel" onClick={() => setEditing(false)} />
              )}
            </div>
          </form>
        )}
      </Section>

      {isConnected && (
        <Section
          title="2. Sync Jira users"
          description="Every active person in Jira gets an account here with the same name, email, avatar and time zone, and joins this workspace. Jira admins become Admins, everyone else a Member. In each imported project people get their Jira project role (Administrators → Admin, Viewers → Client, others → Member, with the role name as their project role). No email is sent; people sign in with their email (login code or “Forgot password”). Run this before syncing projects so work items are assigned to the right people."
        >
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={starting ? "Starting…" : "Sync all users"}
              disabled={starting || isRunning}
              onClick={() => void startUserSync()}
            />
            <span className="text-caption-md-regular text-tertiary">
              Apps, bots and deactivated Jira users are skipped. Jira hides some people&apos;s email: those are listed
              in the sync history and can be invited by hand.
            </span>
          </div>
        </Section>
      )}

      {isConnected && (
        <Section
          title="3. Choose projects and sync"
          description="Each Jira project becomes a project here with the same statuses, so every ticket keeps its Jira status. Syncing again updates what changed in Jira; nothing is duplicated."
        >
          {projectsLoading && <p className="text-body-xs-regular text-tertiary">Loading Jira projects…</p>}
          {projectsError && (
            <p className="text-body-xs-regular text-danger-primary">
              {errorMessage(projectsError, "Could not load Jira projects.")}
            </p>
          )}
          {projects && projects.length === 0 && (
            <p className="text-body-xs-regular text-tertiary">This Jira account cannot see any project.</p>
          )}
          {projects && projects.length > 0 && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <input
                  type="search"
                  className={cn(CONTROL, "w-64")}
                  placeholder="Search by key, name or lead"
                  aria-label="Search Jira projects"
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setPage(1);
                  }}
                />
                <select
                  className={CONTROL}
                  aria-label="Show projects"
                  value={filter}
                  onChange={(event) => {
                    setFilter(event.target.value as TProjectFilter);
                    setPage(1);
                  }}
                >
                  <option value="all">All projects ({projects.length})</option>
                  <option value="new">Not imported yet</option>
                  <option value="imported">Already imported</option>
                </select>
                <span className="ml-auto text-caption-md-regular text-tertiary">
                  {selected.size} selected
                  {selected.size > 0 && (
                    <button
                      type="button"
                      className="ml-2 text-accent-primary hover:underline"
                      onClick={() => setSelected(new Set())}
                    >
                      Clear
                    </button>
                  )}
                </span>
              </div>
              <div className="overflow-x-auto rounded-md border border-subtle">
                <table className="w-full min-w-[640px] text-left text-body-xs-regular">
                  <thead className="text-caption-md-medium text-tertiary">
                    <tr className="border-b border-subtle">
                      <th className="w-10 px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label="Select all listed projects"
                          checked={allFilteredSelected}
                          disabled={filteredKeys.length === 0}
                          onChange={(event) => selectFiltered(event.target.checked)}
                        />
                      </th>
                      <th className="py-2 pr-3 font-medium">Jira project</th>
                      <th className="py-2 pr-3 font-medium">Lead</th>
                      <th className="py-2 pr-3 font-medium">Imported as</th>
                      <th className="py-2 pr-3 font-medium">Last synced</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-3 py-6 text-center text-tertiary">
                          No Jira project matches.
                        </td>
                      </tr>
                    )}
                    {pageItems.map((project) => (
                      <tr key={project.id} className="border-b border-subtle last:border-b-0">
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            aria-label={`Select ${project.name}`}
                            checked={selected.has(project.key)}
                            onChange={() => toggle(project.key)}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          <span className="mr-2 text-caption-md-medium text-tertiary">{project.key}</span>
                          <span className="text-primary">{project.name}</span>
                        </td>
                        <td className="py-2 pr-3 text-secondary">{project.lead ?? "—"}</td>
                        <td className="py-2 pr-3">
                          {project.linked_project ? (
                            <Link
                              className="text-accent-primary hover:underline"
                              href={`/${workspaceSlug}/projects/${project.linked_project.id}/issues`}
                            >
                              {project.linked_project.name}
                            </Link>
                          ) : (
                            <span className="text-tertiary">New project</span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-secondary">{formatDateTime(project.last_synced_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-caption-md-regular text-secondary">
                <span>
                  {filtered.length === 0
                    ? "0 projects"
                    : `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filtered.length)} of ${filtered.length}`}
                </span>
                <label className="flex items-center gap-1.5">
                  Rows per page
                  <select
                    className={cn(CONTROL, "py-1")}
                    value={pageSize}
                    onChange={(event) => {
                      setPageSize(Number(event.target.value));
                      setPage(1);
                    }}
                  >
                    {PAGE_SIZES.map((size) => (
                      <option key={size} value={size}>
                        {size}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    variant="secondary"
                    size="sm"
                    stretch="auto"
                    label="Previous"
                    disabled={currentPage <= 1}
                    onClick={() => setPage(currentPage - 1)}
                  />
                  <span className="px-2">
                    Page {currentPage} of {pageCount}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    stretch="auto"
                    label="Next"
                    disabled={currentPage >= pageCount}
                    onClick={() => setPage(currentPage + 1)}
                  />
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-body-xs-regular text-secondary">
                {(
                  [
                    ["comments", "Comments"],
                    ["history", "Change history"],
                    ["attachments", "Attachments"],
                    ["full", "Full re-sync (also re-read unchanged tickets)"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={options[key]}
                      onChange={(event) => setOptions({ ...options, [key]: event.target.checked })}
                    />
                    {label}
                  </label>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  size="md"
                  stretch="auto"
                  label={starting ? "Starting…" : `Sync selected (${selected.size})`}
                  disabled={starting || isRunning || selected.size === 0}
                  onClick={() => void startSync([...selected])}
                />
                <Button
                  variant="secondary"
                  size="md"
                  stretch="auto"
                  label="Sync all projects"
                  disabled={starting || isRunning || allKeys.length === 0}
                  onClick={() => void startSync(allKeys)}
                />
                {isRunning && (
                  <span className="self-center text-caption-md-regular text-accent-primary">A sync is running…</span>
                )}
              </div>
            </>
          )}
        </Section>
      )}

      <Section
        title="4. Sync history"
        description="Every import with what it brought in, warnings and people that could not be matched."
      >
        {!runs?.length ? (
          <p className="text-body-xs-regular text-tertiary">No sync yet.</p>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <RunCard key={run.id} run={run} workspaceSlug={workspaceSlug} />
            ))}
          </div>
        )}
      </Section>

      <ConfirmDialog
        isOpen={confirmDisconnect}
        handleClose={() => setConfirmDisconnect(false)}
        handleSubmit={async () => {
          setConfirmDisconnect(false);
          await jiraImportService.deleteConnection(workspaceSlug);
          await refreshConnection();
          setForm({ site_url: "", email: "", api_token: "" });
        }}
        title="Disconnect Jira?"
        content="The saved credentials are removed. Projects and work items already imported stay. Nothing in Jira changes."
        isSubmitting={false}
        primaryButtonText={{ default: "Disconnect" }}
      />
    </div>
  );
});
