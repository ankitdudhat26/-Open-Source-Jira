/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Bell, X as CloseIcon } from "lucide-react";
// plane imports
import { IconButton } from "@makeplane/propel/components/icon-button";
import { cn, renderFormattedDate } from "@plane/utils";
// local imports
import type { TNotification } from "./portal-shared";
import { getJson } from "./portal-shared";

type Props = {
  base: string;
  anchor: string;
  /** opens the work item an event is about */
  onOpen: (issueId: string) => void;
};

const KIND_STYLES: Record<string, string> = {
  request_accepted: "bg-success-primary",
  request_declined: "bg-danger-primary",
  request_duplicate: "bg-layer-3",
  request_snoozed: "bg-warning-primary",
};

/** how many of the latest notifications the dropdown shows; the rest are under "View all" */
const LATEST_COUNT = 8;

const seenKey = (anchor: string) => `intake-portal-seen-${anchor}`;

const readSeen = (anchor: string) => {
  try {
    return window.localStorage.getItem(seenKey(anchor)) ?? "";
  } catch {
    return "";
  }
};

/**
 * The bell in the header: what happened to the client's requests (accepted, declined, duplicate) and to their work
 * items (state changes, comments, files from the team), newest first. What is new since they last opened it is counted.
 */
export function NotificationsBell({ base, anchor, onOpen }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  // every notification, full screen ("View all")
  const [isAllOpen, setIsAllOpen] = useState(false);
  const [seen, setSeen] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const { data: events } = useSWR(`${base}notifications/`, (url: string) => getJson<TNotification[]>(url), {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });

  useEffect(() => setSeen(readSeen(anchor)), [anchor]);

  useEffect(() => {
    if (!isOpen) return;
    const onPointer = (event: PointerEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) close();
    };
    document.addEventListener("pointerdown", onPointer, true);
    return () => document.removeEventListener("pointerdown", onPointer, true);
  });

  // Escape closes the full-screen list
  useEffect(() => {
    if (!isAllOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsAllOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isAllOpen]);

  // while the panel is open the count is cleared (everything shown is now seen)
  const unread = isOpen ? 0 : (events ?? []).filter((event) => !seen || event.created_at > seen).length;

  // opening marks everything as seen; the dots of what was new stay until the panel closes
  const close = () => {
    setIsOpen(false);
    setSeen(readSeen(anchor));
  };
  const toggle = () => {
    if (isOpen) return close();
    setIsOpen(true);
    if (events?.length) {
      try {
        window.localStorage.setItem(seenKey(anchor), events[0].created_at);
      } catch {
        // private mode: the count just resets on reload
      }
    }
  };

  const renderEvent = (event: TNotification) => (
    <li key={event.id}>
      <button
        type="button"
        disabled={!event.issue_id}
        onClick={() => {
          if (!event.issue_id) return;
          close();
          setIsAllOpen(false);
          onOpen(event.issue_id);
        }}
        className="flex w-full items-start gap-2.5 px-4 py-3 text-left enabled:hover:bg-layer-1-hover"
      >
        <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", KIND_STYLES[event.kind] ?? "bg-accent-primary")} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-caption-md-medium text-secondary">
            {event.key} · {event.title}
          </span>
          <span className="block text-body-xs-regular break-words text-primary">{event.text}</span>
          <span className="block text-caption-sm-regular text-tertiary">{renderFormattedDate(event.created_at)}</span>
        </span>
        {seen && event.created_at > seen && (
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent-primary" aria-label="New" />
        )}
      </button>
    </li>
  );

  return (
    <div ref={panelRef} className="relative">
      <div className="relative">
        <IconButton
          variant="ghost"
          size="md"
          icon={<Bell className="size-4" />}
          aria-label={unread ? `Notifications, ${unread} new` : "Notifications"}
          aria-expanded={isOpen}
          onClick={toggle}
        />
        {unread > 0 && (
          <span className="pointer-events-none absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-primary px-1 text-[10px] font-medium text-on-color">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </div>
      {isOpen && (
        <div className="absolute top-full right-0 z-40 mt-2 flex max-h-[70vh] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-subtle bg-surface-1 shadow-raised-200">
          <div className="border-b border-subtle px-4 py-2.5 text-body-xs-medium text-primary">Notifications</div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {!events?.length ? (
              <p className="px-4 py-10 text-center text-body-xs-regular text-tertiary">
                Nothing yet. You will see here when the team accepts or declines a request, or works on your items.
              </p>
            ) : (
              <ul className="divide-y divide-subtle">{events.slice(0, LATEST_COUNT).map(renderEvent)}</ul>
            )}
          </div>
          {!!events?.length && (
            <button
              type="button"
              onClick={() => {
                close();
                setIsAllOpen(true);
              }}
              className="border-t border-subtle px-4 py-2.5 text-center text-body-xs-medium text-accent-primary hover:bg-layer-1-hover"
            >
              {events.length > LATEST_COUNT ? `View all notifications (${events.length})` : "View all notifications"}
            </button>
          )}
        </div>
      )}
      {isAllOpen && (
        // every notification, full screen
        <div
          role="dialog"
          aria-modal="true"
          aria-label="All notifications"
          className="fixed inset-0 z-50 flex flex-col bg-canvas"
        >
          <div className="flex items-center justify-between gap-3 border-b border-subtle bg-surface-1 px-5 py-3">
            <div>
              <h2 className="text-body-md-medium text-primary">Notifications</h2>
              <p className="text-caption-md-regular text-tertiary">
                {events?.length ?? 0} {events?.length === 1 ? "notification" : "notifications"}, newest first
              </p>
            </div>
            <IconButton
              variant="ghost"
              size="md"
              icon={<CloseIcon className="size-4" />}
              aria-label="Close notifications"
              onClick={() => setIsAllOpen(false)}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl px-4 py-5">
              {!events?.length ? (
                <p className="py-16 text-center text-body-xs-regular text-tertiary">Nothing yet.</p>
              ) : (
                <ul className="divide-y divide-subtle overflow-hidden rounded-lg border border-subtle bg-surface-1">
                  {events.map(renderEvent)}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
