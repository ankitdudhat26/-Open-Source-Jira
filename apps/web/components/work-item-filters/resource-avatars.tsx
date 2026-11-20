/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { observer } from "mobx-react";
import { UserOutline } from "@makeplane/propel/icons";
// plane imports
import { Avatar } from "@makeplane/propel/components/avatar";
import { Popover, PopoverBody, PopoverContent, PopoverTrigger } from "@makeplane/propel/components/popover";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { IUserLite, TFilterValue } from "@plane/types";
import { COLLECTION_OPERATOR, LOGICAL_OPERATOR } from "@plane/types";
import { cn, getFileURL } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useProjectResources } from "@/hooks/use-project-milestones";
// local imports
import { WORK_ITEM_UNASSIGNED } from "./unassigned";

/** avatars shown before the rest go under "+n" */
const MAX_SHOWN = 6;

type TPerson = { id: string; name: string; avatar?: string; roles: string[] };

type Props = {
  filter: IWorkItemFilterInstance;
  workspaceSlug: string;
  projectId: string;
};

const personLabel = (person: TPerson) =>
  person.roles.length ? `${person.name} · ${person.roles.join(", ")}` : person.name;

const asList = (value: TFilterValue | TFilterValue[] | undefined): string[] =>
  value === undefined || value === null ? [] : (Array.isArray(value) ? value : [value]).map(String);

/** The people filling the project's resources (with their roles); without resources, the project's members. */
export const useResourcePeople = (workspaceSlug: string, projectId: string): TPerson[] => {
  const { resources } = useProjectResources(workspaceSlug, projectId);
  const {
    getUserDetails,
    project: { getProjectMemberIds },
  } = useMember();

  const memberIds = getProjectMemberIds(projectId, false);
  return useMemo<TPerson[]>(() => {
    const byId = new Map<string, TPerson>();
    const add = (user: IUserLite | undefined, role?: string) => {
      if (!user) return;
      const person = byId.get(user.id) ?? {
        id: user.id,
        name: user.display_name || [user.first_name, user.last_name].filter(Boolean).join(" "),
        avatar: user.avatar_url ? getFileURL(user.avatar_url) : undefined,
        roles: [],
      };
      if (role && !person.roles.includes(role)) person.roles.push(role);
      byId.set(user.id, person);
    };
    const filled = (resources ?? []).filter((resource) => resource.member_id);
    if (filled.length) filled.forEach((resource) => add(getUserDetails(resource.member_id ?? ""), resource.role));
    else (memberIds ?? []).forEach((id) => add(getUserDetails(id)));
    return [...byId.values()];
  }, [resources, memberIds, getUserDetails]);
};

/**
 * Opens the filters row of the project's work items once they load, so the resource avatars are there as in Jira
 * (the filter button in the header still hides it). Renders nothing.
 */
export const ShowResourceAvatars = observer(function ShowResourceAvatars(props: Props) {
  const { filter, workspaceSlug, projectId } = props;
  const hasPeople = useResourcePeople(workspaceSlug, projectId).length > 0;
  const shownFor = useRef<string | null>(null);
  useEffect(() => {
    if (!hasPeople || shownFor.current === filter.id) return;
    shownFor.current = filter.id;
    filter.toggleVisibility(true);
  }, [filter, hasPeople]);
  return null;
});

/**
 * The project's resources as avatars above the work items, as in Jira: a click shows only the work items assigned to
 * that person (more clicks add more people), the first one shows the unassigned ones. It is the Assignees filter, so it
 * shows as a filter in the row and works with the other filters.
 */
export const ResourceAvatarsFilter = observer(function ResourceAvatarsFilter(props: Props) {
  const { filter, workspaceSlug, projectId } = props;
  const people = useResourcePeople(workspaceSlug, projectId);
  const [isMoreOpen, setIsMoreOpen] = useState(false);

  // read from the filter's observable conditions (the find helper is an action, which MobX does not track), so the
  // avatars follow every change: a click here, the Assignees filter, Clear all
  const condition = filter.allConditionsForDisplay.find(
    (item) => item.property === "assignee_id" && item.operator === COLLECTION_OPERATOR.IN
  );
  const selected = new Set(asList(condition?.value as TFilterValue | TFilterValue[] | undefined));

  const toggle = (id: string) => {
    const next = selected.has(id) ? [...selected].filter((value) => value !== id) : [...selected, id];
    if (condition) filter.updateConditionValue(condition.id, next);
    else
      filter.addCondition(
        LOGICAL_OPERATOR.AND,
        { property: "assignee_id", operator: COLLECTION_OPERATOR.IN, value: next },
        false
      );
  };

  if (!filter.configManager.areConfigsReady || people.length === 0) return null;

  // the selected ones stay in view even when they are past the first few
  const shown = people.slice(0, MAX_SHOWN);
  const rest = people.slice(MAX_SHOWN);
  const selectedInRest = rest.filter((person) => selected.has(person.id)).length;

  // unselected: a ring in the row's colour, so the overlapping avatars stay apart; selected: a dark ring (light in
  // the dark theme) and raised, as in Jira
  const ring = (isOn: boolean) =>
    cn(
      "relative grid shrink-0 place-items-center rounded-full transition-transform hover:z-20 hover:-translate-y-0.5 focus-visible:z-20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--border-accent-strong)",
      isOn
        ? "z-10 -translate-y-0.5 ring-2 ring-(--txt-primary) ring-offset-[1.5px] ring-offset-(--bg-layer-1)"
        : "ring-2 ring-(--bg-layer-1)"
    );

  return (
    <div className="flex items-center" role="group" aria-label="Filter by resource">
      <div className="flex items-center -space-x-1.5">
        <Tooltip label="Unassigned">
          <button
            type="button"
            aria-pressed={selected.has(WORK_ITEM_UNASSIGNED)}
            aria-label="Unassigned"
            onClick={() => toggle(WORK_ITEM_UNASSIGNED)}
            className={cn(ring(selected.has(WORK_ITEM_UNASSIGNED)), "size-7 bg-layer-3 text-secondary")}
          >
            <UserOutline className="size-4" />
          </button>
        </Tooltip>
        {shown.map((person) => (
          <Tooltip key={person.id} label={personLabel(person)}>
            <button
              type="button"
              aria-pressed={selected.has(person.id)}
              aria-label={person.name}
              onClick={() => toggle(person.id)}
              className={ring(selected.has(person.id))}
            >
              <Avatar size="md" src={person.avatar} alt={person.name} fallback={person.name[0]?.toUpperCase()} />
            </button>
          </Tooltip>
        ))}
        {rest.length > 0 && (
          <Popover open={isMoreOpen} onOpenChange={setIsMoreOpen}>
            <PopoverTrigger
              render={
                <button
                  type="button"
                  aria-label={`${rest.length} more resources`}
                  className={cn(
                    ring(selectedInRest > 0),
                    "size-7 bg-layer-3 text-caption-md-medium text-secondary hover:bg-layer-3-hover"
                  )}
                />
              }
            >
              +{rest.length}
            </PopoverTrigger>
            <PopoverContent variant="rich" side="bottom" align="start" sideOffset={8}>
              <PopoverBody>
                <ul className="-mx-2 max-h-72 w-64 overflow-y-auto">
                  {rest.map((person) => (
                    <li key={person.id}>
                      <button
                        type="button"
                        aria-pressed={selected.has(person.id)}
                        onClick={() => toggle(person.id)}
                        className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left hover:bg-layer-1-hover"
                      >
                        <input
                          type="checkbox"
                          readOnly
                          tabIndex={-1}
                          checked={selected.has(person.id)}
                          className="pointer-events-none"
                          aria-hidden
                        />
                        <Avatar size="sm" src={person.avatar} alt="" fallback={person.name[0]?.toUpperCase()} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-body-xs-medium text-primary">{person.name}</span>
                          {person.roles.length > 0 && (
                            <span className="block truncate text-caption-sm-regular text-tertiary">
                              {person.roles.join(", ")}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </PopoverBody>
            </PopoverContent>
          </Popover>
        )}
      </div>
    </div>
  );
});
