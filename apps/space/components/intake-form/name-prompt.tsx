/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useId, useState } from "react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { Popover, PopoverBody, PopoverContent, PopoverTrigger } from "@makeplane/propel/components/popover";
import { ChevronDownOutline, EditOutline } from "@makeplane/propel/icons";
// local imports
import { send } from "./portal-shared";

/** Saves the client's full name (the team sees requests by it) and returns it as stored. */
const saveFullName = async (base: string, fullName: string) =>
  (await send<{ full_name: string }>(`${base}me/`, "PATCH", { full_name: fullName })).full_name;

type Props = {
  base: string;
  /** called with the saved name */
  onSaved: (fullName: string) => void;
};

/**
 * For a client whose account has no name yet (made before the sign-up form asked for it): the team sees requests by
 * this name instead of the email, so it is asked once, above the tabs.
 */
export function FullNamePrompt({ base, onSaved }: Props) {
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const inputId = useId();

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!fullName.trim()) return;
    setIsSaving(true);
    setError("");
    try {
      onSaved(await saveFullName(base, fullName));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void save(event)}
      className="flex flex-col gap-3 rounded-lg border border-accent-subtle bg-accent-subtle/40 p-4 sm:flex-row sm:items-end"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor={inputId} className="text-body-xs-medium text-primary">
          Add your full name
        </label>
        <p className="text-caption-md-regular text-tertiary">
          The team sees this name on your requests instead of your email.
        </p>
        <div className="mt-1">
          <InputGroup size="lg">
            <Input
              id={inputId}
              size="lg"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder="e.g. Manish Singh"
              autoComplete="name"
              maxLength={200}
            />
          </InputGroup>
        </div>
        {error && <p className="text-caption-md-regular text-danger-primary">{error}</p>}
      </div>
      <Button
        type="submit"
        variant="primary"
        size="lg"
        stretch="auto"
        label={isSaving ? "Saving..." : "Save name"}
        disabled={isSaving || !fullName.trim()}
      />
    </form>
  );
}

type TEditNameMenuProps = {
  base: string;
  /** the saved name ("" when there is none yet) */
  fullName: string;
  email: string;
  onSaved: (fullName: string) => void;
};

/**
 * In the header: the client's name (or email, until they give one). A click opens a small form to change the name the
 * team sees on their requests; every client can change it at any time.
 */
export function EditNameMenu({ base, fullName, email, onSaved }: TEditNameMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  // the panel shows the name; the pencil turns it into a field to change it
  const [isEditing, setIsEditing] = useState(false);
  const [value, setValue] = useState(fullName);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const inputId = useId();

  // each time it opens, it shows the saved name (not a field)
  useEffect(() => {
    if (!isOpen) return;
    setIsEditing(false);
    setValue(fullName);
    setError("");
  }, [isOpen, fullName]);

  const startEditing = () => {
    setValue(fullName);
    setError("");
    setIsEditing(true);
  };

  const isUnchanged = value.trim().replace(/\s+/g, " ") === fullName;

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!value.trim() || isUnchanged) return;
    setIsSaving(true);
    setError("");
    try {
      onSaved(await saveFullName(base, value));
      setIsEditing(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            title={email}
            aria-label={`Your name: ${fullName || "not set"}`}
            className="flex max-w-56 items-center gap-1.5 rounded-sm px-1.5 py-1 text-body-xs-regular text-secondary hover:bg-layer-1-hover"
          />
        }
      >
        <span className="truncate">{fullName || email}</span>
        <ChevronDownOutline className="size-3.5 shrink-0 text-tertiary" />
      </PopoverTrigger>
      <PopoverContent variant="rich" side="bottom" align="end" sideOffset={8}>
        <PopoverBody>
          <div className="flex w-72 flex-col gap-3">
            <span className="text-caption-md-medium text-tertiary">Your name</span>
            {isEditing ? (
              <form onSubmit={(event) => void save(event)} className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <label htmlFor={inputId} className="text-caption-md-medium text-secondary">
                    Full name
                  </label>
                  <InputGroup size="lg">
                    <Input
                      id={inputId}
                      size="lg"
                      value={value}
                      onChange={(event) => setValue(event.target.value)}
                      placeholder="e.g. Manish Singh"
                      autoComplete="name"
                      maxLength={200}
                      // oxlint-disable-next-line jsx-a11y/no-autofocus -- opened on purpose by the edit button
                      autoFocus
                    />
                  </InputGroup>
                  <span className="text-caption-sm-regular text-tertiary">
                    The team sees this name on your requests.
                  </span>
                  {error && <span className="text-caption-md-regular text-danger-primary">{error}</span>}
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    size="md"
                    stretch="auto"
                    label="Cancel"
                    onClick={() => setIsEditing(false)}
                  />
                  <Button
                    type="submit"
                    variant="primary"
                    size="md"
                    stretch="auto"
                    label={isSaving ? "Saving..." : "Save"}
                    disabled={isSaving || !value.trim() || isUnchanged}
                  />
                </div>
              </form>
            ) : (
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <p
                    className={
                      fullName ? "truncate text-body-sm-medium text-primary" : "text-body-sm-regular text-tertiary"
                    }
                  >
                    {fullName || "No name yet"}
                  </p>
                  <p className="truncate text-caption-md-regular text-tertiary">{email}</p>
                </div>
                <IconButton
                  variant="ghost"
                  size="md"
                  icon={<EditOutline />}
                  aria-label={fullName ? "Edit name" : "Add name"}
                  onClick={startEditing}
                />
              </div>
            )}
          </div>
        </PopoverBody>
      </PopoverContent>
    </Popover>
  );
}
