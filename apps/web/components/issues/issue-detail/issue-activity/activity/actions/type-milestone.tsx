/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { InboxOutline, LayerStackOutline, MilestoneOutline } from "@makeplane/propel/icons";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// components
import { IssueActivityBlockComponent } from "./";

type TIssueTypeMilestoneActivity = { activityId: string; ends: "top" | "bottom" | undefined };

/** Change of the work item type (Feature / Task / Bug), its milestone or its queue (e.g. DevOps). */
export const IssueTypeMilestoneActivity = observer(function IssueTypeMilestoneActivity(
  props: TIssueTypeMilestoneActivity
) {
  const { activityId, ends } = props;
  // hooks
  const {
    activity: { getActivityById },
  } = useIssueDetail();

  const activity = getActivityById(activityId);
  if (!activity) return <></>;

  const isType = activity.field === "type";
  const isQueue = activity.field === "queue";
  const label = isType ? "type" : "milestone";
  const Icon = isQueue ? InboxOutline : isType ? LayerStackOutline : MilestoneOutline;

  if (isQueue)
    return (
      <IssueActivityBlockComponent
        icon={<Icon className="h-3.5 w-3.5 text-secondary" aria-hidden="true" />}
        activityId={activityId}
        ends={ends}
      >
        {activity.new_value ? (
          <>
            sent the work item to the <span className="font-medium text-primary">{activity.new_value}</span> queue.
          </>
        ) : (
          <>
            removed the work item from the <span className="font-medium text-primary">{activity.old_value}</span> queue.
          </>
        )}
      </IssueActivityBlockComponent>
    );

  return (
    <IssueActivityBlockComponent
      icon={<Icon className="h-3.5 w-3.5 text-secondary" aria-hidden="true" />}
      activityId={activityId}
      ends={ends}
    >
      {activity.new_value ? (
        <>
          set the {label} to <span className="font-medium text-primary">{activity.new_value}</span>.
        </>
      ) : (
        <>
          removed the {label} <span className="font-medium text-primary">{activity.old_value}</span>.
        </>
      )}
    </IssueActivityBlockComponent>
  );
});
