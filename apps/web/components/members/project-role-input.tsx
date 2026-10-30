/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import {
  Autocomplete,
  AutocompleteContent,
  AutocompleteInputGroup,
  AutocompleteItem,
  AutocompleteList,
} from "@makeplane/propel/components/autocomplete";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import type { AutocompleteSize } from "@makeplane/propel/components/autocomplete";
import { ChevronDownOutline } from "@makeplane/propel/icons";

/** Common jobs on a project. Any other title can be typed. */
export const PROJECT_ROLE_SUGGESTIONS = [
  "Project Manager",
  "Business Analyst",
  "Developer",
  "Frontend Developer",
  "Backend Developer",
  "Full Stack Developer",
  "Mobile Developer",
  "UI/UX Designer",
  "Graphic Designer",
  "QA Engineer",
  "DevOps Engineer",
  "Client",
];

type Props = {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  invalid?: boolean;
  disabled?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  size?: AutocompleteSize;
};

/** The person's job on the project ("Developer", "Graphic Designer", ...): pick a suggestion or type any title. */
export function ProjectRoleInput(props: Props) {
  const {
    value,
    onChange,
    onBlur,
    invalid,
    disabled,
    placeholder = "Project role",
    ariaLabel = "Project role",
    size = "md",
  } = props;
  return (
    <Autocomplete<string>
      items={PROJECT_ROLE_SUGGESTIONS}
      value={value}
      onValueChange={(nextValue) => onChange(nextValue)}
      openOnInputClick
      disabled={disabled}
    >
      <AutocompleteInputGroup
        size={size}
        placeholder={placeholder}
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        onBlur={onBlur}
        maxLength={255}
        trigger={
          <IconButton
            variant="ghost"
            size="xs"
            icon={<Icon icon={ChevronDownOutline} />}
            aria-label="Show role suggestions"
          />
        }
      />
      <AutocompleteContent side="bottom" align="start">
        <AutocompleteList>
          {(role: string) => (
            <AutocompleteItem key={role} value={role} size="md">
              {role}
            </AutocompleteItem>
          )}
        </AutocompleteList>
      </AutocompleteContent>
    </Autocomplete>
  );
}
