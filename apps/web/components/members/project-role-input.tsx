/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useId } from "react";
import { Input, InputGroup } from "@makeplane/propel/components/input";

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
};

/** The person's job on the project ("Developer", "Graphic Designer", ...), with suggestions. */
export function ProjectRoleInput(props: Props) {
  const {
    value,
    onChange,
    onBlur,
    invalid,
    disabled,
    placeholder = "Project role",
    ariaLabel = "Project role",
  } = props;
  const listId = useId();
  return (
    <InputGroup size="md">
      <Input
        size="md"
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        disabled={disabled}
        list={listId}
        maxLength={255}
        autoComplete="off"
      />
      <datalist id={listId}>
        {PROJECT_ROLE_SUGGESTIONS.map((suggestion) => (
          <option key={suggestion} value={suggestion} />
        ))}
      </datalist>
    </InputGroup>
  );
}
