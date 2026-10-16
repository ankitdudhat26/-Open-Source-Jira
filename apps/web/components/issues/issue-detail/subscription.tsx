/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { isNil } from "lodash-es";
import { observer } from "mobx-react";
import useSWR from "swr";
import { ShowFilled, ShowOutline } from "@makeplane/propel/icons";
// plane-i18n
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// UI
import { Button } from "@makeplane/propel/elements/button";
import { Icon } from "@makeplane/propel/components/icon";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { setToast } from "@plane/blocks/toast";
import { EIssueServiceType } from "@plane/types";
import { Loader } from "@plane/blocks/skeleton";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useUserPermissions } from "@/hooks/store/user";

export type TIssueSubscription = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  serviceType?: EIssueServiceType;
};

export const IssueSubscription = observer(function IssueSubscription(props: TIssueSubscription) {
  const { workspaceSlug, projectId, issueId, serviceType = EIssueServiceType.ISSUES } = props;
  const { t } = useTranslation();
  // hooks
  const {
    subscription: { getSubscriptionByIssueId, getWatcherIdsByIssueId },
    createSubscription,
    removeSubscription,
    fetchWatchers,
  } = useIssueDetail(serviceType);
  const { getUserDetails } = useMember();
  // state
  const [loading, setLoading] = useState(false);
  // hooks
  const { allowPermissions } = useUserPermissions();

  // watchers (shared SWR key with the Watchers property in the sidebar)
  useSWR(
    workspaceSlug && projectId && issueId ? `ISSUE_WATCHERS_${workspaceSlug}_${projectId}_${issueId}` : null,
    workspaceSlug && projectId && issueId ? () => fetchWatchers(workspaceSlug, projectId, issueId) : null,
    { revalidateOnFocus: false }
  );

  const isSubscribed = getSubscriptionByIssueId(issueId);
  const watcherIds = getWatcherIdsByIssueId(issueId);
  const watcherNames = (watcherIds ?? [])
    .map((userId) => getUserDetails(userId)?.display_name)
    .filter((name): name is string => !!name);
  const isEditable = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );

  const handleSubscription = async () => {
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
      setLoading(false);
    } catch {
      setLoading(false);
      setToast({
        type: "error",
        title: t("toast.error"),
        message: t("common.error.message"),
      });
    }
  };

  if (isNil(isSubscribed))
    return (
      <Loader>
        <Loader.Item width="106px" height="28px" />
      </Loader>
    );

  return (
    <Tooltip
      label={
        watcherNames.length > 0
          ? `Watchers (${watcherNames.length}): ${watcherNames.join(", ")}`
          : "No one is watching this work item yet."
      }
    >
      <Button
        variant="secondary"
        size="md"
        stretch="auto"
        render={<button type="button" />}
        onClick={handleSubscription}
        disabled={!isEditable || loading}
        aria-pressed={isSubscribed}
      >
        <Icon icon={isSubscribed ? ShowFilled : ShowOutline} />
        <span className="hidden sm:block">{loading ? t("common.loading") : isSubscribed ? "Watching" : "Watch"}</span>
        {watcherIds && (
          <span className="rounded-sm bg-layer-2 px-1.5 text-caption-sm-medium text-secondary">
            {watcherIds.length}
          </span>
        )}
      </Button>
    </Tooltip>
  );
});
