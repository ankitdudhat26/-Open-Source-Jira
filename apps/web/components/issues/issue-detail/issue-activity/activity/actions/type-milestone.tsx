/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { LayerStackOutline, MilestoneOutline } from "@makeplane/propel/icons";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// components
import { IssueActivityBlockComponent } from "./";

type TIssueTypeMilestoneActivity = { activityId: string; ends: "top" | "bottom" | undefined };

/** Change of the work item type (Feature / Task / Bug) or of its milestone. */
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
  const label = isType ? "type" : "milestone";
  const Icon = isType ? LayerStackOutline : MilestoneOutline;

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
