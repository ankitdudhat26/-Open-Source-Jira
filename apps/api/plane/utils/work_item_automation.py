# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Jira style automation for the Feature -> Task hierarchy.

* Status: a parent follows its children. When every child is done the parent moves to the project's first
  "completed" state; when work starts on a child the parent moves to the first "started" state; when a child of a
  done parent is reopened (or a new open child is added) the parent goes back to "started".
* Sprint (cycle): children always sit in their parent's sprint. Adding a feature to a sprint brings all of its tasks
  along, removing it takes them out, and a task created under (or moved to) a feature that is in a sprint joins it.

Every function is idempotent, so the same change can be checked both in the request (so the UI is up to date at
once) and again in the activity task (which also covers bulk updates, the public API and imports).
"""

import json

from django.core import serializers
from django.utils import timezone

from plane.db.models import CycleIssue, Issue, State, StateGroup

DONE_GROUPS = {StateGroup.COMPLETED.value, StateGroup.CANCELLED.value}
WORK_STARTED_GROUPS = {StateGroup.STARTED.value, StateGroup.COMPLETED.value}
NOT_STARTED_GROUPS = {StateGroup.BACKLOG.value, StateGroup.UNSTARTED.value}

# guards against a broken (cyclic) parent chain
MAX_DEPTH = 20


def _first_state(project_id, group):
    return State.objects.filter(project_id=project_id, group=group).order_by("sequence", "created_at").first()


def target_parent_state(parent):
    """State the parent should move to based on its children, or None when it is already right."""
    child_groups = list(Issue.issue_objects.filter(parent_id=parent.id).values_list("state__group", flat=True))
    if not child_groups:
        return None
    parent_group = parent.state.group if parent.state_id else None
    all_done = all(group in DONE_GROUPS for group in child_groups)

    if all_done:
        # only cancelled children: nothing was delivered, leave the parent as it is
        if StateGroup.COMPLETED.value in child_groups and parent_group != StateGroup.COMPLETED.value:
            return _first_state(parent.project_id, StateGroup.COMPLETED.value)
        return None
    if parent_group in NOT_STARTED_GROUPS and any(group in WORK_STARTED_GROUPS for group in child_groups):
        return _first_state(parent.project_id, StateGroup.STARTED.value)
    if parent_group == StateGroup.COMPLETED.value:
        # a child was reopened or a new open child was added
        return _first_state(parent.project_id, StateGroup.STARTED.value)
    return None


def sync_ancestor_states(parent_id, actor_id, origin=None):
    """Re-evaluate ``parent_id`` and its ancestors. Returns the ids of the work items whose state changed."""
    from plane.bgtasks.issue_activities_task import issue_activity

    changed = []
    seen = set()
    while parent_id and str(parent_id) not in seen and len(seen) < MAX_DEPTH:
        seen.add(str(parent_id))
        parent = Issue.issue_objects.filter(pk=parent_id).select_related("state").first()
        if parent is None:
            break
        new_state = target_parent_state(parent)
        if new_state is None or new_state.id == parent.state_id:
            # nothing changed here, so the ancestors above are unaffected too
            break
        old_state_id = parent.state_id
        parent.state = new_state
        parent.save(update_fields=["state", "updated_at"])
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"state_id": str(new_state.id)}),
            actor_id=str(actor_id),
            issue_id=str(parent.id),
            project_id=str(parent.project_id),
            current_instance=json.dumps({"state_id": str(old_state_id) if old_state_id else None}),
            epoch=int(timezone.now().timestamp()),
            notification=True,
            # the person who moved the task does not start watching the feature because of the automation
            subscriber=False,
            origin=origin,
        )
        changed.append(str(parent.id))
        parent_id = parent.parent_id
    return changed


def descendant_ids(issue_ids, project_id):
    """Ids of all children, grandchildren, ... of the given work items (not including them)."""
    found = []
    seen = {str(issue_id) for issue_id in issue_ids}
    frontier = list(seen)
    for _ in range(MAX_DEPTH):
        if not frontier:
            break
        children = [
            str(child_id)
            for child_id in Issue.issue_objects.filter(project_id=project_id, parent_id__in=frontier).values_list(
                "id", flat=True
            )
        ]
        frontier = [child_id for child_id in children if child_id not in seen]
        seen.update(frontier)
        found.extend(frontier)
    return found


def assign_issues_to_cycle(cycle, issue_ids, actor_id, origin=None):
    """Put the work items in ``cycle`` (moving them out of any other cycle) and log the activity.

    Returns the ids that were added or moved.
    """
    from plane.bgtasks.issue_activities_task import issue_activity

    issue_ids = [str(issue_id) for issue_id in issue_ids]
    if not issue_ids:
        return []
    project_id = cycle.project_id
    valid_ids = {
        str(issue_id)
        for issue_id in Issue.issue_objects.filter(project_id=project_id, pk__in=issue_ids).values_list("id", flat=True)
    }
    existing = list(CycleIssue.objects.filter(project_id=project_id, issue_id__in=valid_ids))
    to_move = [record for record in existing if record.cycle_id != cycle.id]
    in_some_cycle = {str(record.issue_id) for record in existing}
    to_create = sorted(valid_ids - in_some_cycle)

    created_records = CycleIssue.objects.bulk_create(
        [
            CycleIssue(
                project_id=project_id,
                workspace_id=cycle.workspace_id,
                created_by_id=actor_id,
                updated_by_id=actor_id,
                cycle_id=cycle.id,
                issue_id=issue_id,
            )
            for issue_id in to_create
        ],
        batch_size=100,
    )
    moved_activity = []
    for record in to_move:
        moved_activity.append(
            {"old_cycle_id": str(record.cycle_id), "new_cycle_id": str(cycle.id), "issue_id": str(record.issue_id)}
        )
        record.cycle_id = cycle.id
    CycleIssue.objects.bulk_update(to_move, ["cycle_id"], batch_size=100)

    changed = to_create + [item["issue_id"] for item in moved_activity]
    if changed:
        issue_activity.delay(
            type="cycle.activity.created",
            requested_data=json.dumps({"cycles_list": changed}),
            actor_id=str(actor_id),
            issue_id=None,
            project_id=str(project_id),
            current_instance=json.dumps(
                {
                    "updated_cycle_issues": moved_activity,
                    "created_cycle_issues": serializers.serialize("json", created_records),
                }
            ),
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=origin,
        )
    return changed


def remove_issues_from_cycle(cycle_id, issue_ids, project_id, actor_id, origin=None):
    """Take the work items out of the cycle and log the activity. Returns the removed ids."""
    from plane.bgtasks.issue_activities_task import issue_activity

    records = CycleIssue.objects.filter(cycle_id=cycle_id, project_id=project_id, issue_id__in=issue_ids)
    removed = [str(issue_id) for issue_id in records.values_list("issue_id", flat=True)]
    for issue_id in removed:
        issue_activity.delay(
            type="cycle.activity.deleted",
            requested_data=json.dumps({"cycle_id": str(cycle_id), "issues": [issue_id]}),
            actor_id=str(actor_id),
            issue_id=issue_id,
            project_id=str(project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=origin,
        )
    records.delete()
    return removed


def inherit_parent_cycle(issue_id, actor_id, origin=None):
    """A child joins its parent's sprint (only while that sprint is not finished)."""
    issue = Issue.issue_objects.filter(pk=issue_id).first()
    if issue is None or issue.parent_id is None:
        return []
    parent_cycle = (
        CycleIssue.objects.filter(issue_id=issue.parent_id, project_id=issue.project_id).select_related("cycle").first()
    )
    if parent_cycle is None or not is_cycle_open(parent_cycle.cycle):
        return []
    if CycleIssue.objects.filter(issue_id=issue.id, cycle_id=parent_cycle.cycle_id).exists():
        return []
    # the child's own children follow it
    ids = [str(issue.id), *descendant_ids([issue.id], issue.project_id)]
    return assign_issues_to_cycle(parent_cycle.cycle, ids, actor_id, origin)


def is_cycle_open(cycle):
    return (
        cycle is not None and cycle.archived_at is None and (cycle.end_date is None or cycle.end_date >= timezone.now())
    )


def run_work_item_automation(
    issue_id, actor_id, origin=None, state_changed=False, parent_changed=False, old_parent_id=None
):
    """Run the automation for one changed work item. Returns the ids of other work items that were changed."""
    issue = Issue.issue_objects.filter(pk=issue_id).first()
    if issue is None:
        return []
    changed = []
    if parent_changed:
        changed += inherit_parent_cycle(issue.id, actor_id, origin)
        if old_parent_id and str(old_parent_id) != str(issue.parent_id):
            changed += sync_ancestor_states(old_parent_id, actor_id, origin)
    if (state_changed or parent_changed) and issue.parent_id:
        changed += sync_ancestor_states(issue.parent_id, actor_id, origin)
    return [issue_id for issue_id in dict.fromkeys(changed) if issue_id != str(issue.id)]
