/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { orderBy } from "lodash-es";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { Button } from "@makeplane/propel/components/button";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import {
  ArrowDownOutline,
  ArrowUpOutline,
  LinkOutline,
  MoreHorizontalOutline,
  SearchOutline,
  SettingsOutline,
  WorkItemsOutline,
} from "@makeplane/propel/icons";
import { EUserPermissions } from "@plane/constants";
import { FavoriteStar } from "@plane/blocks/common";
import { Logo } from "@plane/blocks/emoji-icon-picker";
import { setPromiseToast, setToast } from "@plane/blocks/toast";
import type { TProject, TProjectType } from "@plane/types";
import { cn, copyUrlToClipboard, getFileURL, renderFormattedDate } from "@plane/utils";
// components
import { PROJECT_TYPE_OPTIONS } from "@/components/project/create/commercial-attributes";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { useUser, useUserPermissions } from "@/hooks/store/user";

const PAGE_SIZES = [25, 50, 100];
const CONTROL = "rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary";

type TSortKey = "name" | "identifier" | "created_at";
type TTypeFilter = "all" | TProjectType | "none";

const typeLabel = (type: TProjectType | undefined) =>
  PROJECT_TYPE_OPTIONS.find((option) => option.key === type)?.label ?? "—";

type TAllProjectsRootProps = {
  workspaceSlug: string;
  /** "all": every project of the workspace (the admin-only All projects page); "mine": only the projects the
   * signed-in user is a member of (the Projects page) */
  scope?: "all" | "mine";
};

/** Projects of the workspace in one table, like Jira's "Spaces" list. */
export const AllProjectsRoot = observer(function AllProjectsRoot(props: TAllProjectsRootProps) {
  const { workspaceSlug, scope = "all" } = props;
  // store hooks
  const { workspaceProjectIds, getProjectById, addProjectToFavorites, removeProjectFromFavorites } = useProject();
  const { getUserDetails } = useMember();
  const { workspaceInfoBySlug } = useUserPermissions();
  const { data: currentUser } = useUser();
  // states
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<TTypeFilter>("all");
  const [sort, setSort] = useState<{ key: TSortKey; desc: boolean }>({ key: "name", desc: false });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[1]);
  // derived values
  const isWorkspaceAdmin = workspaceInfoBySlug(workspaceSlug)?.role === EUserPermissions.ADMIN;
  const query = search.trim().toLowerCase();
  const matching = (workspaceProjectIds ?? [])
    .map((projectId) => getProjectById(projectId))
    .filter((project): project is TProject => !!project)
    // "mine": the projects the user is a member of or leads
    .filter(
      (project) =>
        scope === "all" || !!project.member_role || (!!currentUser && project.project_lead === currentUser.id)
    )
    .filter(
      (project) =>
        !query || project.name.toLowerCase().includes(query) || project.identifier.toLowerCase().includes(query)
    )
    .filter(
      (project) =>
        typeFilter === "all" || (typeFilter === "none" ? !project.project_type : project.project_type === typeFilter)
    );
  const projects = orderBy(
    matching,
    [
      (project) =>
        sort.key === "created_at" ? new Date(project.created_at ?? 0).getTime() : project[sort.key].toLowerCase(),
    ],
    [sort.desc ? "desc" : "asc"]
  );
  const pageCount = Math.max(1, Math.ceil(projects.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageItems = projects.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const toggleSort = (key: TSortKey) => setSort((current) => ({ key, desc: current.key === key && !current.desc }));

  const toggleFavorite = (project: TProject) => {
    const promise = project.is_favorite
      ? removeProjectFromFavorites(workspaceSlug, project.id)
      : addProjectToFavorites(workspaceSlug, project.id);
    setPromiseToast(promise, {
      loading: project.is_favorite ? "Removing project from favorites..." : "Adding project to favorites...",
      success: {
        title: "Success!",
        message: () => (project.is_favorite ? "Project removed from favorites." : "Project added to favorites."),
      },
      error: { title: "Error!", message: () => "Couldn't update favorites. Please try again." },
    });
  };

  const copyLink = (project: TProject) =>
    void copyUrlToClipboard(`${workspaceSlug}/projects/${project.id}/issues`).then(() =>
      setToast({ type: "success", title: "Link copied", message: `Link to ${project.name} copied to clipboard.` })
    );

  const SortHeader = ({ label, sortKey }: { label: string; sortKey: TSortKey }) => (
    <button
      type="button"
      className="inline-flex items-center gap-1 font-medium hover:text-primary"
      onClick={() => toggleSort(sortKey)}
      aria-label={`Sort by ${label}`}
    >
      {label}
      {sort.key === sortKey && (
        <span className="flex size-3.5">
          <Icon icon={sort.desc ? ArrowUpOutline : ArrowDownOutline} />
        </span>
      )}
    </button>
  );

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-y-auto px-page-x py-5">
      <div>
        <h2 className="text-h4-semibold text-primary">{scope === "all" ? "All projects" : "Projects"}</h2>
        <p className="mt-1 text-body-xs-regular text-tertiary">
          {scope === "all" ? "Every project in this workspace." : "The projects you lead or are a member of."}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className={cn(CONTROL, "flex w-64 items-center gap-1.5")}>
          <span className="flex size-4 text-tertiary">
            <Icon icon={SearchOutline} />
          </span>
          <input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Search projects"
            aria-label="Search projects by name or key"
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-placeholder"
          />
        </label>
        <select
          className={CONTROL}
          value={typeFilter}
          onChange={(event) => {
            setTypeFilter(event.target.value as TTypeFilter);
            setPage(1);
          }}
          aria-label="Filter by project type"
        >
          <option value="all">All types</option>
          {PROJECT_TYPE_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
          <option value="none">No type</option>
        </select>
      </div>

      <div className="overflow-x-auto rounded-lg border border-subtle">
        <table className="w-full min-w-[860px] text-left text-body-xs-regular">
          <thead className="bg-layer-1 text-caption-md-medium text-secondary">
            <tr className="border-b border-subtle">
              <th className="w-10 py-2.5 pl-3" aria-label="Favorite" />
              <th className="py-2.5 pr-3">
                <SortHeader label="Name" sortKey="name" />
              </th>
              <th className="py-2.5 pr-3">
                <SortHeader label="Key" sortKey="identifier" />
              </th>
              <th className="py-2.5 pr-3 font-medium">Type</th>
              <th className="py-2.5 pr-3 font-medium">Access</th>
              <th className="py-2.5 pr-3 font-medium">Lead</th>
              <th className="py-2.5 pr-3">
                <SortHeader label="Created" sortKey="created_at" />
              </th>
              <th className="w-12 py-2.5 pr-3" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {pageItems.length === 0 && (
              <tr>
                <td colSpan={8} className="py-10 text-center text-tertiary">
                  {workspaceProjectIds === undefined
                    ? "Loading projects…"
                    : scope === "mine" && !query && typeFilter === "all"
                      ? "You are not a member of any project yet."
                      : "No projects match."}
                </td>
              </tr>
            )}
            {pageItems.map((project) => {
              const lead = typeof project.project_lead === "string" ? getUserDetails(project.project_lead) : undefined;
              const isMember = !!project.member_role;
              const canManage = isWorkspaceAdmin || project.member_role === EUserPermissions.ADMIN;
              return (
                <tr
                  key={project.id}
                  className="border-b border-subtle last:border-b-0 hover:bg-layer-transparent-hover"
                >
                  <td className="py-2 pl-3">
                    {isMember && (
                      <FavoriteStar
                        buttonClassName="size-6 rounded-sm"
                        iconClassName="size-3.5"
                        selected={!!project.is_favorite}
                        onClick={() => toggleFavorite(project)}
                      />
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <Link
                      href={`/${workspaceSlug}/projects/${project.id}/issues`}
                      className="flex min-w-0 items-center gap-2 font-medium text-accent-primary hover:underline"
                    >
                      <span className="grid size-6 shrink-0 place-items-center rounded-sm bg-layer-2">
                        <Logo logo={project.logo_props} size={14} />
                      </span>
                      <span className="truncate">{project.name}</span>
                    </Link>
                  </td>
                  <td className="py-2 pr-3 font-medium text-primary">{project.identifier}</td>
                  <td className="py-2 pr-3 text-secondary">{typeLabel(project.project_type)}</td>
                  <td className="py-2 pr-3 text-secondary">{project.network === 2 ? "Public" : "Private"}</td>
                  <td className="py-2 pr-3">
                    {lead ? (
                      <span className="flex min-w-0 items-center gap-2 text-primary">
                        <Avatar
                          alt={lead.display_name}
                          fallback={lead.display_name?.[0]?.toUpperCase()}
                          src={getFileURL(lead.avatar_url ?? "")}
                          size="sm"
                        />
                        <span className="truncate">{lead.display_name}</span>
                      </span>
                    ) : (
                      <span className="text-tertiary">—</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-secondary">
                    {project.created_at ? renderFormattedDate(project.created_at) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <Menu>
                      <MenuTrigger
                        render={
                          <IconButton
                            variant="tertiary"
                            size="md"
                            icon={<Icon icon={MoreHorizontalOutline} />}
                            aria-label={`Options for ${project.name}`}
                          />
                        }
                      />
                      <MenuContent side="bottom" align="end">
                        <MenuItem
                          icon={<Icon icon={WorkItemsOutline} />}
                          label="Open work items"
                          render={<Link href={`/${workspaceSlug}/projects/${project.id}/issues`} />}
                        />
                        {canManage && (
                          <MenuItem
                            icon={<Icon icon={SettingsOutline} />}
                            label="Project settings"
                            render={<Link href={`/${workspaceSlug}/settings/projects/${project.id}`} />}
                          />
                        )}
                        <MenuItem
                          icon={<Icon icon={LinkOutline} />}
                          label="Copy link"
                          onClick={() => copyLink(project)}
                        />
                      </MenuContent>
                    </Menu>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-caption-md-regular text-secondary">
        <span>
          {projects.length === 0
            ? "0 projects"
            : `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, projects.length)} of ${projects.length} projects`}
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
    </div>
  );
});
