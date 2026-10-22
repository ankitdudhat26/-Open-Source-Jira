/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { Button } from "@makeplane/propel/components/button";
import { cn, getFileURL, renderFormattedDate } from "@plane/utils";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// hooks
import { useProject } from "@/hooks/store/use-project";
// services
import type { THistoryEntry, THistoryFilters } from "@/services/jira-import.service";
import { jiraImportService } from "@/services/jira-import.service";

type Props = { workspaceSlug: string };

const FIELD_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Any change" },
  { value: "created", label: "Created" },
  { value: "state", label: "Status" },
  { value: "assignees", label: "Assignee" },
  { value: "priority", label: "Priority" },
  { value: "name", label: "Title" },
  { value: "description", label: "Description" },
  { value: "comment", label: "Comments" },
  { value: "labels", label: "Labels" },
  { value: "cycles", label: "Sprint" },
  { value: "modules", label: "Module" },
  { value: "target_date", label: "Due date" },
  { value: "start_date", label: "Start date" },
  { value: "parent", label: "Parent" },
  { value: "attachment", label: "Attachments" },
];

const FIELD_LABELS: Record<string, string> = Object.fromEntries(
  FIELD_OPTIONS.filter((option) => option.value).map((option) => [option.value, option.label])
);

const CONTROL = "rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary";

function describe(entry: THistoryEntry) {
  if (!entry.field && entry.verb === "created") return entry.comment || "created the work item";
  const label = entry.field_label || FIELD_LABELS[entry.field ?? ""] || (entry.field ?? "").replace(/_/g, " ");
  if (entry.field === "comment") return entry.verb === "created" ? "added a comment" : `${entry.verb} a comment`;
  if (entry.field === "description") return "updated the description";
  if (entry.old_value && entry.new_value) return `changed ${label}`;
  if (entry.new_value) return `set ${label}`;
  if (entry.old_value) return `removed ${label}`;
  return entry.comment || `changed ${label}`;
}

/** Every change to work items: who changed what and when, including history imported from Jira. */
export const HistoryRoot = observer(function HistoryRoot(props: Props) {
  const { workspaceSlug } = props;
  const { joinedProjectIds, getProjectById } = useProject();
  const [filters, setFilters] = useState<THistoryFilters>({});
  const [search, setSearch] = useState("");
  const [entries, setEntries] = useState<THistoryEntry[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    jiraImportService
      .getHistory(workspaceSlug, filters, page)
      .then((data) => {
        if (!active) return null;
        setEntries((current) => (page === 1 ? data.results : [...current, ...data.results]));
        setHasMore(data.has_more);
        return null;
      })
      .catch(() => setHasMore(false))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [workspaceSlug, filters, page]);

  const update = (change: Partial<THistoryFilters>) => {
    setPage(1);
    setFilters((current) => ({ ...current, ...change }));
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <form
        className="flex flex-wrap items-center gap-2 border-b border-subtle px-page-x py-3"
        onSubmit={(event) => {
          event.preventDefault();
          update({ search });
        }}
      >
        <select
          className={CONTROL}
          aria-label="Project"
          value={filters.project_id ?? ""}
          onChange={(event) => update({ project_id: event.target.value })}
        >
          <option value="">All projects</option>
          {(joinedProjectIds ?? []).map((id) => (
            <option key={id} value={id}>
              {getProjectById(id)?.name}
            </option>
          ))}
        </select>
        <div className="w-44">
          <MemberSelect
            value={filters.actor_id ?? null}
            onChange={(id) => update({ actor_id: id === filters.actor_id ? "" : id })}
            variant="select-ghost-md"
            placeholder="Anyone"
            tooltip={{ heading: "Changed by" }}
          />
        </div>
        <select
          className={CONTROL}
          aria-label="What changed"
          value={filters.field ?? ""}
          onChange={(event) => update({ field: event.target.value })}
        >
          {FIELD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          className={CONTROL}
          aria-label="Source"
          value={filters.source ?? ""}
          onChange={(event) => update({ source: event.target.value as THistoryFilters["source"] })}
        >
          <option value="">All sources</option>
          <option value="jira">Imported from Jira</option>
        </select>
        <input
          type="date"
          className={CONTROL}
          aria-label="From date"
          value={filters.from ?? ""}
          onChange={(event) => update({ from: event.target.value })}
        />
        <input
          type="date"
          className={CONTROL}
          aria-label="To date"
          value={filters.to ?? ""}
          onChange={(event) => update({ to: event.target.value })}
        />
        <input
          type="search"
          className={cn(CONTROL, "w-48")}
          placeholder="Search work items"
          aria-label="Search work items"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {Object.values(filters).some(Boolean) && (
          <button
            type="button"
            className="text-caption-md-medium text-accent-primary"
            onClick={() => {
              setSearch("");
              setPage(1);
              setFilters({});
            }}
          >
            Clear filters
          </button>
        )}
      </form>

      <div className="flex-1 overflow-auto">
        {entries.length === 0 && !loading && (
          <p className="px-page-x py-10 text-center text-body-xs-regular text-tertiary">No changes match.</p>
        )}
        {entries.length > 0 && (
          <table className="w-full min-w-[820px] text-left text-body-xs-regular">
            <thead className="sticky top-0 z-[1] bg-surface-1 text-caption-md-medium text-tertiary">
              <tr className="border-b border-subtle">
                <th className="px-page-x py-2 font-medium">When</th>
                <th className="py-2 pr-3 font-medium">Who</th>
                <th className="py-2 pr-3 font-medium">Work item</th>
                <th className="py-2 pr-3 font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="border-b border-subtle align-top">
                  <td className="px-page-x py-2.5 whitespace-nowrap text-secondary">
                    {renderFormattedDate(entry.created_at)}{" "}
                    <span className="text-tertiary">
                      {new Date(entry.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3">
                    {entry.actor_name && entry.from_jira ? (
                      <span className="text-primary">{entry.actor_name}</span>
                    ) : entry.actor ? (
                      <span className="flex items-center gap-1.5 text-primary">
                        <Avatar
                          alt={entry.actor.display_name}
                          fallback={entry.actor.display_name?.[0]?.toUpperCase()}
                          src={getFileURL(entry.actor.avatar_url ?? "")}
                          size="sm"
                        />
                        {entry.actor.display_name}
                      </span>
                    ) : (
                      <span className="text-tertiary">{entry.from_jira ? "Jira user" : "System"}</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-3">
                    <Link
                      className="hover:underline"
                      href={`/${workspaceSlug}/projects/${entry.project.id}/issues/${entry.issue.id}`}
                    >
                      <span className="mr-1.5 text-caption-md-medium text-tertiary">
                        {entry.project.identifier}-{entry.issue.sequence_id}
                      </span>
                      <span className="text-primary">{entry.issue.name}</span>
                    </Link>
                    <span className="block text-caption-sm-regular text-tertiary">{entry.project.name}</span>
                  </td>
                  <td className="py-2.5 pr-3">
                    <span className="text-secondary">{describe(entry)}</span>
                    {!["description", "comment"].includes(entry.field ?? "") &&
                      (entry.old_value || entry.new_value) && (
                        <span className="ml-1.5">
                          {entry.old_value && <span className="text-tertiary line-through">{entry.old_value}</span>}
                          {entry.old_value && entry.new_value && <span className="text-tertiary"> → </span>}
                          {entry.new_value && <span className="font-medium text-primary">{entry.new_value}</span>}
                        </span>
                      )}
                    {entry.from_jira && (
                      <span className="ml-2 rounded-sm bg-layer-3 px-1.5 text-caption-sm-regular text-tertiary">
                        Jira
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {loading && <p className="px-page-x py-4 text-body-xs-regular text-tertiary">Loading…</p>}
        {hasMore && !loading && (
          <div className="px-page-x py-4">
            <Button variant="secondary" size="sm" stretch="auto" label="Load more" onClick={() => setPage(page + 1)} />
          </div>
        )}
      </div>
    </div>
  );
});
