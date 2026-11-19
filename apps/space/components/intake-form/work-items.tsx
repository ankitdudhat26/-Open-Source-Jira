/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Icon } from "@makeplane/propel/components/icon";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import {
  CalendarOutline,
  CyclesOutline,
  LabelsOutline,
  MembersOutline,
  ModuleOutline,
  PriorityOutline,
  SearchOutline,
  StateOutline,
  UserOutline,
} from "@makeplane/propel/icons";
import { EIconSize } from "@plane/constants";
import { PriorityIcon, StateGroupIcon } from "@plane/blocks/icons";
import type { TIssuePriorities } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
// local imports
import type { TOption, TWorkItemRow } from "./portal-shared";
import { ColorDot, LabelChip, OptionSelect, PRIORITY_LABELS, initials } from "./portal-shared";

type Props = {
  items: TWorkItemRow[];
  showProject: boolean;
  onOpen: (id: string) => void;
};

type TFilters = { types: string[]; states: string[]; assignees: string[]; priorities: string[]; creators: string[] };
const NO_FILTERS: TFilters = { types: [], states: [], assignees: [], priorities: [], creators: [] };
// "Created by me": the client's own work items (their requests), whoever they are
const ME = "me";
const PRIORITY_ORDER: TIssuePriorities[] = ["urgent", "high", "medium", "low", "none"];

/** A column title with the property's icon, as in the app's spreadsheet. */
function Th({ icon, children, className }: { icon?: React.ReactNode; children: string; className?: string }) {
  return (
    <th className={`border-r border-subtle px-4 py-2.5 font-medium last:border-r-0 ${className ?? ""}`}>
      <span className="flex items-center gap-1.5">
        {icon}
        {children}
      </span>
    </th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <td className={`border-r border-subtle px-4 py-2.5 text-body-xs-regular last:border-r-0 ${className ?? ""}`}>
      {children}
    </td>
  );
}

const Empty = () => <span className="text-placeholder">—</span>;

/** The work item's type as the app shows it: a small square in the type's colour. */
function TypeMark({ item }: { item: TWorkItemRow }) {
  if (!item.type) return <span className="size-3.5 shrink-0" />;
  return (
    <span
      className="flex size-3.5 shrink-0 items-center justify-center rounded-[3px]"
      style={{ backgroundColor: `${item.type.color}22`, border: `1px solid ${item.type.color}` }}
      title={item.type.name}
    >
      <span className="size-1.5 rounded-full" style={{ backgroundColor: item.type.color }} />
    </span>
  );
}

/**
 * The project's work items, laid out like the app's spreadsheet (type, ID and title; state, priority, assignees,
 * labels, modules, sprint and dates) with the app's filters: type, state, assignees and priority, and a search.
 * Opening one shows its details, where the client comments and moves its state.
 */
export function WorkItemsTable({ items, showProject, onOpen }: Props) {
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<TFilters>(NO_FILTERS);

  // the choices of each filter: what the work items have
  const options = useMemo(() => {
    const unique = (list: TOption[]) => [...new Map(list.map((option) => [option.id, option])).values()];
    return {
      types: unique(
        items.flatMap((item) =>
          item.type ? [{ id: item.type.name, name: item.type.name, color: item.type.color }] : []
        )
      ),
      states: unique(items.flatMap((item) => (item.state ? [item.state] : []))),
      // a sorted copy (toSorted needs ES2023)
      // oxlint-disable-next-line unicorn/no-array-sort
      assignees: [...unique(items.flatMap((item) => item.assignees))].sort((a, b) => a.name.localeCompare(b.name)),
      priorities: PRIORITY_ORDER.map((priority) => ({ id: priority, name: PRIORITY_LABELS[priority] })),
      creators: [
        ...(items.some((item) => item.is_mine) ? [{ id: ME, name: "Created by me" }] : []),
        ...unique(items.flatMap((item) => (item.created_by && !item.is_mine ? [item.created_by] : []))),
      ],
    };
  }, [items]);
  // the work items' states, with their group and colour for the icons
  const stateById = useMemo(
    () => new Map(items.flatMap((item) => (item.state ? [[item.state.id, item.state] as const] : []))),
    [items]
  );

  const query = search.trim().toLowerCase();
  const visible = items.filter(
    (item) =>
      (!filters.types.length || (item.type && filters.types.includes(item.type.name))) &&
      (!filters.states.length || (item.state && filters.states.includes(item.state.id))) &&
      (!filters.assignees.length || item.assignees.some((person) => filters.assignees.includes(person.id))) &&
      (!filters.priorities.length || filters.priorities.includes(item.priority)) &&
      (!filters.creators.length ||
        (item.is_mine && filters.creators.includes(ME)) ||
        (!!item.created_by && filters.creators.includes(item.created_by.id))) &&
      (!query || `${item.key} ${item.name}`.toLowerCase().includes(query))
  );
  const filtered = Object.values(filters).some((values) => values.length > 0) || !!query;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-44">
          <OptionSelect
            multiple
            size="md"
            options={options.types}
            placeholder="Type"
            icon={(option) => <ColorDot color={option.color} />}
            value={filters.types}
            onChange={(values) => setFilters((current) => ({ ...current, types: values }))}
          />
        </div>
        <div className="w-44">
          <OptionSelect
            multiple
            size="md"
            options={options.states}
            placeholder="State"
            icon={(option) => {
              const state = stateById.get(option.id);
              return state ? <StateGroupIcon stateGroup={state.group} color={state.color} size={EIconSize.SM} /> : null;
            }}
            value={filters.states}
            onChange={(values) => setFilters((current) => ({ ...current, states: values }))}
          />
        </div>
        <div className="w-44">
          <OptionSelect
            multiple
            size="md"
            options={options.assignees}
            placeholder="Assignees"
            icon={(option) => (
              <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[8px] font-medium text-on-color">
                {initials(option.name)}
              </span>
            )}
            value={filters.assignees}
            onChange={(values) => setFilters((current) => ({ ...current, assignees: values }))}
          />
        </div>
        <div className="w-44">
          <OptionSelect
            multiple
            size="md"
            options={options.priorities}
            placeholder="Priority"
            icon={(option) => <PriorityIcon priority={option.id as TIssuePriorities} className="size-3.5" />}
            value={filters.priorities}
            onChange={(values) => setFilters((current) => ({ ...current, priorities: values }))}
          />
        </div>
        <div className="w-44">
          <OptionSelect
            multiple
            size="md"
            options={options.creators}
            placeholder="Created by"
            icon={(option) => (
              <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[8px] font-medium text-on-color">
                {option.id === ME ? "Me" : initials(option.name)}
              </span>
            )}
            value={filters.creators}
            onChange={(values) => setFilters((current) => ({ ...current, creators: values }))}
          />
        </div>
        {filtered && (
          <Button
            variant="ghost"
            size="md"
            stretch="auto"
            label="Clear filters"
            onClick={() => {
              setFilters(NO_FILTERS);
              setSearch("");
            }}
          />
        )}
        <div className="ml-auto w-full sm:w-64">
          <InputGroup size="md">
            <Icon icon={SearchOutline} />
            <Input
              size="md"
              value={search}
              placeholder="Search work items"
              aria-label="Search work items"
              onChange={(event) => setSearch(event.target.value)}
            />
          </InputGroup>
        </div>
      </div>
      <p className="text-caption-md-regular text-tertiary">
        {filtered ? `${visible.length} of ${items.length} work items` : `${items.length} work items`}
      </p>

      <div className="overflow-hidden rounded-lg border border-subtle bg-surface-1">
        {visible.length === 0 ? (
          <p className="px-5 py-14 text-center text-body-xs-regular text-tertiary">
            {items.length === 0 ? "No work items yet." : "No work items match these filters."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1580px] text-left">
              <thead className="border-b border-subtle text-body-xs-medium text-secondary">
                <tr>
                  <Th className="w-[30%]">Work items</Th>
                  {showProject && <Th className="w-40">Project</Th>}
                  <Th icon={<StateOutline className="size-3.5" />} className="w-44">
                    State
                  </Th>
                  <Th icon={<PriorityOutline className="size-3.5" />} className="w-32">
                    Priority
                  </Th>
                  <Th icon={<MembersOutline className="size-3.5" />} className="w-44">
                    Assignees
                  </Th>
                  <Th icon={<LabelsOutline className="size-3.5" />} className="w-48">
                    Labels
                  </Th>
                  <Th icon={<ModuleOutline className="size-3.5" />} className="w-40">
                    Modules
                  </Th>
                  <Th icon={<CyclesOutline className="size-3.5" />} className="w-36">
                    Sprint
                  </Th>
                  <Th icon={<CalendarOutline className="size-3.5" />} className="w-32">
                    Start date
                  </Th>
                  <Th icon={<CalendarOutline className="size-3.5" />} className="w-32">
                    Due date
                  </Th>
                  <Th icon={<UserOutline className="size-3.5" />} className="w-44">
                    Created by
                  </Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-subtle">
                {visible.map((item) => (
                  <tr
                    key={item.id}
                    className="cursor-pointer hover:bg-layer-1-hover focus-visible:outline focus-visible:outline-accent-strong"
                    tabIndex={0}
                    onClick={() => onOpen(item.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") onOpen(item.id);
                    }}
                  >
                    <Td>
                      <span className="flex min-w-0 items-center gap-2">
                        <TypeMark item={item} />
                        <span className="w-24 shrink-0 text-caption-md-medium text-tertiary">{item.key}</span>
                        <span className="truncate text-primary">{item.name}</span>
                      </span>
                    </Td>
                    {showProject && <Td className="text-secondary">{item.project_name}</Td>}
                    <Td className="text-primary">
                      {item.state ? (
                        <span className="flex items-center gap-1.5">
                          <StateGroupIcon stateGroup={item.state.group} color={item.state.color} size={EIconSize.MD} />
                          <span className="truncate">{item.state.name}</span>
                        </span>
                      ) : (
                        <Empty />
                      )}
                    </Td>
                    <Td className="text-primary">
                      <span className="flex items-center gap-1.5">
                        <PriorityIcon priority={item.priority} className="size-3.5" />
                        {PRIORITY_LABELS[item.priority] ?? "None"}
                      </span>
                    </Td>
                    <Td className="text-primary">
                      {item.assignees.length === 0 ? (
                        <Empty />
                      ) : (
                        <span className="flex items-center gap-1.5">
                          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[9px] font-medium text-on-color">
                            {initials(item.assignees[0].name)}
                          </span>
                          <span className="truncate">
                            {item.assignees[0].name}
                            {item.assignees.length > 1 && ` +${item.assignees.length - 1}`}
                          </span>
                        </span>
                      )}
                    </Td>
                    <Td>
                      {item.labels.length === 0 ? (
                        <Empty />
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {item.labels.slice(0, 2).map((label) => (
                            <LabelChip key={label.id} label={label} />
                          ))}
                          {item.labels.length > 2 && (
                            <span className="text-caption-sm-regular text-tertiary">+{item.labels.length - 2}</span>
                          )}
                        </span>
                      )}
                    </Td>
                    <Td className="text-primary">
                      {item.modules.length ? (
                        <span className="block truncate">{item.modules.map((module) => module.name).join(", ")}</span>
                      ) : (
                        <Empty />
                      )}
                    </Td>
                    <Td className="text-primary">
                      {item.sprint ? <span className="block truncate">{item.sprint.name}</span> : <Empty />}
                    </Td>
                    <Td className="whitespace-nowrap text-primary">
                      {item.start_date ? renderFormattedDate(item.start_date) : <Empty />}
                    </Td>
                    <Td className="whitespace-nowrap text-primary">
                      {item.target_date ? renderFormattedDate(item.target_date) : <Empty />}
                    </Td>
                    <Td className="text-primary">
                      {item.created_by ? (
                        <span className="flex items-center gap-1.5">
                          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[9px] font-medium text-on-color">
                            {initials(item.created_by.name)}
                          </span>
                          <span className="truncate">{item.is_mine ? "You" : item.created_by.name}</span>
                        </span>
                      ) : (
                        <Empty />
                      )}
                    </Td>
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
