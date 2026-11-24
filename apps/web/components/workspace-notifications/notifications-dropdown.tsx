/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Bell } from "lucide-react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Popover, PopoverContent, PopoverTrigger } from "@makeplane/propel/components/popover";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import type { TNotification } from "@plane/types";
import { cn, generateWorkItemLink, renderFormattedDate } from "@plane/utils";
// hooks
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useAppRouter } from "@/hooks/use-app-router";
// services
import workspaceNotificationService from "@/services/workspace-notification.service";
// local imports
import { NotificationContent } from "./sidebar/notification-card/content";

/** how many of the latest notifications the dropdown shows; the rest are under "View all" */
const LATEST_COUNT = 8;

type Props = {
  workspaceSlug: string;
  /** unread notifications, for the badge */
  unreadCount: number;
  isActive?: boolean;
};

/** Where a notification leads: the work item, or the request in Intake. */
const notificationLink = (workspaceSlug: string, notification: TNotification) => {
  const issue = notification.data?.issue;
  if (!issue?.id || !notification.project) return `/${workspaceSlug}/notifications/`;
  if (notification.is_inbox_issue)
    return `/${workspaceSlug}/projects/${notification.project}/intake?currentTab=open&inboxIssueId=${issue.id}`;
  return generateWorkItemLink({
    workspaceSlug,
    projectId: notification.project,
    issueId: issue.id,
    projectIdentifier: issue.identifier,
    sequenceId: issue.sequence_id,
  });
};

/**
 * The bell in the top bar, as on the client portal: the latest notifications in a dropdown (newest first, the unread
 * ones marked), mark all as read, and "View all" for the full notifications page.
 */
export const NotificationsDropdown = observer(function NotificationsDropdown(props: Props) {
  const { workspaceSlug, unreadCount, isActive = false } = props;
  const router = useAppRouter();
  const [isOpen, setIsOpen] = useState(false);
  const { getUnreadNotificationsCount } = useWorkspaceNotifications();
  const { getWorkspaceBySlug } = useWorkspace();
  const workspace = getWorkspaceBySlug(workspaceSlug);

  // read each time it opens, so it is current
  const { data, isLoading, mutate } = useSWR(
    isOpen ? ["NOTIFICATIONS_DROPDOWN", workspaceSlug] : null,
    () =>
      workspaceNotificationService.fetchNotifications(workspaceSlug, {
        archived: false,
        snoozed: false,
        per_page: LATEST_COUNT,
        cursor: `${LATEST_COUNT}:0:0`,
      }),
    { revalidateOnMount: true, revalidateOnFocus: false }
  );
  const notifications = (data?.results ?? []).filter((item) => item.data?.issue_activity?.field);
  const total = data?.total_count ?? notifications.length;

  const refreshCount = () => void getUnreadNotificationsCount(workspaceSlug);

  const openNotification = async (notification: TNotification) => {
    setIsOpen(false);
    if (!notification.read_at) {
      try {
        await workspaceNotificationService.markNotificationAsRead(workspaceSlug, notification.id);
        refreshCount();
      } catch {
        // still open it
      }
    }
    router.push(notificationLink(workspaceSlug, notification));
  };

  const markAllAsRead = async () => {
    try {
      await workspaceNotificationService.markAllNotificationsAsRead(workspaceSlug, {
        archived: false,
        snoozed: false,
      });
      await mutate();
      refreshCount();
    } catch {
      // the badge stays as it is
    }
  };

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <Tooltip label="Notifications" side="bottom" disabled={isOpen}>
        <PopoverTrigger
          render={
            <button
              type="button"
              aria-label={unreadCount ? `Notifications, ${unreadCount} unread` : "Notifications"}
              className={cn(
                "relative flex size-8 items-center justify-center rounded-md text-secondary hover:bg-layer-1-hover",
                { "bg-layer-1-hover text-primary": isOpen || isActive }
              )}
            />
          }
        >
          <Bell className="size-[18px]" />
          {unreadCount > 0 && (
            <span className="pointer-events-none absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-primary px-1 text-[10px] font-medium text-on-color">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent side="bottom" align="end" sideOffset={8}>
        <div className="flex max-h-[70vh] w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-subtle px-4 py-2.5">
            <span className="text-body-xs-medium text-primary">Notifications</span>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={() => void markAllAsRead()}
                className="text-caption-md-medium text-accent-primary hover:underline"
              >
                Mark all as read
              </button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {isLoading && !data ? (
              <p className="px-4 py-10 text-center text-body-xs-regular text-tertiary">Loading…</p>
            ) : notifications.length === 0 ? (
              <p className="px-4 py-10 text-center text-body-xs-regular text-tertiary">
                Nothing yet. You will see here when someone works on the work items you follow.
              </p>
            ) : (
              <ul className="divide-y divide-subtle">
                {notifications.map((notification) => {
                  const issue = notification.data?.issue;
                  const isUnread = !notification.read_at;
                  return (
                    <li key={notification.id}>
                      <button
                        type="button"
                        onClick={() => void openNotification(notification)}
                        className={cn("flex w-full items-start gap-2.5 px-4 py-3 text-left hover:bg-layer-1-hover", {
                          "bg-accent-primary/5": isUnread,
                        })}
                      >
                        <span
                          className={cn(
                            "mt-1.5 size-2 shrink-0 rounded-full",
                            isUnread ? "bg-accent-primary" : "bg-layer-3"
                          )}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-caption-md-medium text-secondary">
                            {issue ? `${issue.identifier}-${issue.sequence_id} · ${issue.name}` : "Work item"}
                          </span>
                          <span className="line-clamp-2 block text-body-xs-regular break-words text-primary">
                            {workspace && notification.project ? (
                              <NotificationContent
                                notification={notification}
                                workspaceId={workspace.id}
                                workspaceSlug={workspaceSlug}
                                projectId={notification.project}
                              />
                            ) : null}
                          </span>
                          <span className="block text-caption-sm-regular text-tertiary">
                            {renderFormattedDate(notification.created_at)}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              setIsOpen(false);
              router.push(`/${workspaceSlug}/notifications/`);
            }}
            className="border-t border-subtle px-4 py-2.5 text-center text-body-xs-medium text-accent-primary hover:bg-layer-1-hover"
          >
            {total > notifications.length ? `View all notifications (${total})` : "View all notifications"}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
});
