/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Checkbox } from "@makeplane/propel/components/checkbox";
import { CircleDashedOutline } from "@makeplane/propel/icons";
// plane imports
import { EIconSize } from "@plane/constants";
import { StateGroupIcon } from "@plane/blocks/icons";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
// local imports
import { FiltersDropdown } from "./issue-layouts/filters";

type Props = {
  projectId: string;
  hiddenStateIds: string[];
  onChange: (hiddenStateIds: string[]) => void;
};

/**
 * "Statuses" next to Display on the project's work items: uncheck a status to hide its work items and its column.
 * Saved for the person, in this project only.
 */
export const StatusVisibilityDropdown = observer(function StatusVisibilityDropdown(props: Props) {
  const { projectId, hiddenStateIds, onChange } = props;
  const { getProjectStates } = useProjectState();
  const states = getProjectStates(projectId) ?? [];
  // a status deleted since it was hidden does not count
  const hidden = hiddenStateIds.filter((id) => states.some((state) => state.id === id));
  const shownCount = states.length - hidden.length;

  const toggle = (stateId: string, show: boolean) => {
    const next = show ? hidden.filter((id) => id !== stateId) : [...hidden, stateId];
    // at least one status stays visible
    if (next.length >= states.length) return;
    onChange(next);
  };

  return (
    <FiltersDropdown
      miniIcon={<CircleDashedOutline className="size-3.5" />}
      title={hidden.length ? `Statuses (${shownCount}/${states.length})` : "Statuses"}
      placement="bottom-end"
      isFiltersApplied={hidden.length > 0}
    >
      <div className="flex w-64 flex-col gap-1 p-2">
        <div className="flex items-center justify-between px-1 pb-1">
          <span className="text-caption-md-medium text-tertiary">Show work items in</span>
          <button
            type="button"
            className="text-caption-md-medium text-accent-primary disabled:text-placeholder"
            disabled={hidden.length === 0}
            onClick={() => onChange([])}
          >
            Show all
          </button>
        </div>
        <div className="vertical-scrollbar scrollbar-sm flex max-h-80 flex-col overflow-y-auto">
          {states.map((state) => {
            const isShown = !hidden.includes(state.id);
            return (
              <div
                key={state.id}
                className="flex items-center gap-2 rounded-sm px-1 py-1.5 hover:bg-layer-transparent-hover"
              >
                <Checkbox
                  checked={isShown}
                  // the last visible status cannot be hidden
                  disabled={isShown && shownCount === 1}
                  onCheckedChange={(checked) => toggle(state.id, checked)}
                  aria-label={`Show ${state.name}`}
                />
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 text-left text-body-xs-regular text-primary"
                  disabled={isShown && shownCount === 1}
                  onClick={() => toggle(state.id, !isShown)}
                >
                  <StateGroupIcon stateGroup={state.group} color={state.color} size={EIconSize.MD} />
                  <span className="truncate">{state.name}</span>
                </button>
              </div>
            );
          })}
        </div>
        <p className="px-1 pt-1 text-caption-sm-regular text-placeholder">
          Unchecked statuses and their work items are hidden for you, in this project only.
        </p>
      </div>
    </FiltersDropdown>
  );
});
