/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { isNil } from "lodash-es";
import { observer } from "mobx-react";
import useSWR from "swr";
import { AddOutline, CloseOutline, ShowFilled, ShowOutline } from "@makeplane/propel/icons";
// plane-i18n
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// UI
import { Avatar } from "@makeplane/propel/components/avatar";
import { Button } from "@makeplane/propel/elements/button";
import { Icon } from "@makeplane/propel/components/icon";
import { Popover, PopoverContent, PopoverTrigger } from "@makeplane/propel/components/popover";
import { Shortcut } from "@makeplane/propel/components/shortcut";
import { setToast } from "@plane/blocks/toast";
import { EIssueServiceType } from "@plane/types";
import { Loader } from "@plane/blocks/skeleton";
import { getFileURL } from "@plane/utils";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useUser, useUserPermissions } from "@/hooks/store/user";

export type TIssueSubscription = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  serviceType?: EIssueServiceType;
};

const ROW = "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-body-xs-regular text-primary";
const ROW_ACTION = `${ROW} hover:bg-layer-transparent-hover disabled:cursor-not-allowed disabled:opacity-60`;

/** Typing in a field (title, description, comment...) never toggles watching. */
const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/**
 * Jira style watching: the eye with the number of watchers opens a panel to start / stop watching (also the
 * W key), see who watches the work item and add or remove watchers. Watchers get notified of comments and changes.
 */
export const IssueSubscription = observer(function IssueSubscription(props: TIssueSubscription) {
  const { workspaceSlug, projectId, issueId, serviceType = EIssueServiceType.ISSUES } = props;
  const { t } = useTranslation();
  // hooks
  const {
    subscription: { getSubscriptionByIssueId, getWatcherIdsByIssueId },
    createSubscription,
    removeSubscription,
    fetchWatchers,
    addWatchers,
    removeWatcher,
  } = useIssueDetail(serviceType);
  const {
    getUserDetails,
    project: { getProjectMemberIds },
  } = useMember();
  const { data: currentUser } = useUser();
  const { allowPermissions } = useUserPermissions();
  // state
  const [loading, setLoading] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // watchers (shared SWR key with the Watchers property in the sidebar)
  useSWR(
    workspaceSlug && projectId && issueId ? `ISSUE_WATCHERS_${workspaceSlug}_${projectId}_${issueId}` : null,
    workspaceSlug && projectId && issueId ? () => fetchWatchers(workspaceSlug, projectId, issueId) : null,
    { revalidateOnFocus: false }
  );

  const isSubscribed = getSubscriptionByIssueId(issueId);
  const watcherIds = getWatcherIdsByIssueId(issueId) ?? [];
  const isEditable = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );
  // project members not watching yet, for "Add watchers"
  const query = search.trim().toLowerCase();
  const candidates = (getProjectMemberIds(projectId, false) ?? [])
    .filter((userId) => !watcherIds.includes(userId))
    .map((userId) => getUserDetails(userId))
    .filter((user) => !!user)
    .filter(
      (user) =>
        !query ||
        user.display_name?.toLowerCase().includes(query) ||
        `${user.first_name ?? ""} ${user.last_name ?? ""}`.toLowerCase().includes(query)
    )
    .slice(0, 8);

  const showError = (error?: unknown) =>
    setToast({
      type: "error",
      title: t("toast.error"),
      message:
        error && typeof error === "object" && "error" in error && typeof error.error === "string"
          ? error.error
          : t("common.error.message"),
    });

  const handleSubscription = async () => {
    if (!isEditable || loading) return;
    setLoading(true);
    try {
      if (isSubscribed) await removeSubscription(workspaceSlug, projectId, issueId);
      else await createSubscription(workspaceSlug, projectId, issueId);
      setToast({
        type: "success",
        title: t("toast.success"),
        message: isSubscribed
          ? "You stopped watching this work item."
          : "You are watching this work item. You will get an email for new comments and changes.",
      });
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async (userId: string) => {
    try {
      await addWatchers(workspaceSlug, projectId, issueId, [userId]);
      setSearch("");
    } catch (error) {
      showError(error);
    }
  };

  const handleRemove = async (userId: string) => {
    try {
      await removeWatcher(workspaceSlug, projectId, issueId, userId);
    } catch (error) {
      showError(error);
    }
  };

  useEffect(() => {
    if (isAdding) searchRef.current?.focus();
  }, [isAdding]);

  // W starts / stops watching, like in Jira
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "w" || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (event.repeat || isTyping(event.target) || isTyping(document.activeElement)) return;
      event.preventDefault();
      void handleSubscription();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  if (isNil(isSubscribed))
    return (
      <Loader>
        <Loader.Item width="48px" height="28px" />
      </Loader>
    );

  return (
    <Popover
      onOpenChange={(open) => {
        if (!open) {
          setIsAdding(false);
          setSearch("");
        }
      }}
    >
      <PopoverTrigger
        render={
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            render={<button type="button" />}
            aria-label={`Watch options: ${isSubscribed ? "you are watching" : "you are not watching"} this work item, ${watcherIds.length} watching`}
          >
            <Icon icon={isSubscribed ? ShowFilled : ShowOutline} />
            <span className="text-caption-md-medium tabular-nums">{watcherIds.length}</span>
          </Button>
        }
      />
      <PopoverContent variant="rich" side="bottom" align="end">
        <div className="-m-1 flex w-64 flex-col">
          <button
            type="button"
            className={ROW_ACTION}
            onClick={() => void handleSubscription()}
            disabled={!isEditable || loading}
            aria-keyshortcuts="W"
          >
            <span className="flex text-accent-primary">
              <Icon icon={isSubscribed ? ShowFilled : ShowOutline} />
            </span>
            <span className="flex-1 font-medium">
              {loading ? t("common.loading") : isSubscribed ? "Stop watching" : "Start watching"}
            </span>
            <Shortcut keys="W" />
          </button>

          <div className="my-1 border-t border-subtle" />
          <p className="px-2 pt-1 pb-1.5 text-caption-sm-medium text-tertiary">Watching this work item</p>
          <div className="max-h-56 overflow-y-auto">
            {watcherIds.length === 0 && (
              <p className="px-2 py-1.5 text-body-xs-regular text-tertiary">No one is watching yet.</p>
            )}
            {watcherIds.map((userId) => {
              const user = getUserDetails(userId);
              const name = user?.display_name || "Unknown user";
              return (
                <div key={userId} className={`group ${ROW}`}>
                  <Avatar
                    alt={name}
                    fallback={name[0]?.toUpperCase()}
                    src={getFileURL(user?.avatar_url ?? "")}
                    size="sm"
                  />
                  <span className="flex-1 truncate">
                    {name}
                    {userId === currentUser?.id && <span className="text-tertiary"> (You)</span>}
                  </span>
                  {isEditable && (
                    <button
                      type="button"
                      className="grid size-5 place-items-center rounded-sm text-tertiary opacity-0 group-hover:opacity-100 hover:bg-layer-transparent-hover hover:text-primary focus-visible:opacity-100"
                      onClick={() => void handleRemove(userId)}
                      aria-label={`Remove ${name} from watchers`}
                    >
                      <Icon icon={CloseOutline} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {isEditable && (
            <>
              <div className="my-1 border-t border-subtle" />
              {isAdding ? (
                <div className="flex flex-col gap-1">
                  <input
                    ref={searchRef}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search people"
                    aria-label="Search people to add as watchers"
                    className="mx-1 rounded-md border border-subtle bg-layer-1 px-2 py-1.5 text-body-xs-regular text-primary outline-none focus:border-accent-strong"
                  />
                  <div className="max-h-48 overflow-y-auto">
                    {candidates.length === 0 && (
                      <p className="px-2 py-1.5 text-body-xs-regular text-tertiary">No people to add.</p>
                    )}
                    {candidates.map((user) => (
                      <button
                        key={user.id}
                        type="button"
                        className={ROW_ACTION}
                        onClick={() => void handleAdd(user.id)}
                      >
                        <Avatar
                          alt={user.display_name}
                          fallback={user.display_name?.[0]?.toUpperCase()}
                          src={getFileURL(user.avatar_url ?? "")}
                          size="sm"
                        />
                        <span className="flex-1 truncate">{user.display_name}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <button type="button" className={ROW_ACTION} onClick={() => setIsAdding(true)}>
                  <Icon icon={AddOutline} />
                  <span className="flex-1 font-medium">Add watchers</span>
                </button>
              )}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
});
