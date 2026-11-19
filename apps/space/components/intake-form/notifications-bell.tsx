/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Bell } from "lucide-react";
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
              <ul className="divide-y divide-subtle">
                {events.map((event) => (
                  <li key={event.id}>
                    <button
                      type="button"
                      disabled={!event.issue_id}
                      onClick={() => {
                        if (!event.issue_id) return;
                        close();
                        onOpen(event.issue_id);
                      }}
                      className="flex w-full items-start gap-2.5 px-4 py-3 text-left enabled:hover:bg-layer-1-hover"
                    >
                      <span
                        className={cn(
                          "mt-1.5 size-2 shrink-0 rounded-full",
                          KIND_STYLES[event.kind] ?? "bg-accent-primary"
                        )}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-caption-md-medium text-secondary">
                          {event.key} · {event.title}
                        </span>
                        <span className="block text-body-xs-regular break-words text-primary">{event.text}</span>
                        <span className="block text-caption-sm-regular text-tertiary">
                          {renderFormattedDate(event.created_at)}
                        </span>
                      </span>
                      {seen && event.created_at > seen && (
                        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent-primary" aria-label="New" />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
