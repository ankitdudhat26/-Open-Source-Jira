# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Jira style project workflows: which state a work item may move to next, and who may move it.

* The workflow is off until a project admin enables it.
* A state with no rules is not restricted: its work items can move to any state.
* A state with rules only allows the listed target states.
* A rule can name reviewers; then only they (and project admins) can make that change.
* Automation (a feature following its tasks) is not blocked by the workflow, like Jira's automation actor.
"""

from django.db import transaction

from plane.db.models import ProjectMember, ProjectWorkflow, State, WorkflowTransition
from plane.utils.uuid import is_valid_uuid

ADMIN_ROLE = 20

WORKFLOW_TEMPLATES = {
    "software": {
        "name": "Software development",
        "description": "Backlog → To Do → In Progress → In Review → QA → Done, with Cancelled from any state.",
        "states": [
            {"name": "Backlog", "group": "backlog", "color": "#A3A3A3"},
            {"name": "To Do", "group": "unstarted", "color": "#3A3A3A"},
            {"name": "In Progress", "group": "started", "color": "#F59E0B"},
            {"name": "In Review", "group": "started", "color": "#8B5CF6"},
            {"name": "QA", "group": "started", "color": "#0EA5E9"},
            {"name": "Done", "group": "completed", "color": "#16A34A"},
            {"name": "Cancelled", "group": "cancelled", "color": "#9AA4BC"},
        ],
        "transitions": {
            "Backlog": ["To Do", "Cancelled"],
            "To Do": ["In Progress", "Backlog", "Cancelled"],
            "In Progress": ["In Review", "To Do", "Cancelled"],
            "In Review": ["QA", "In Progress", "Cancelled"],
            "QA": ["Done", "In Progress", "Cancelled"],
            "Done": ["In Progress"],
            "Cancelled": ["Backlog"],
        },
    },
    "simple": {
        "name": "Simple",
        "description": "To Do → In Progress → Done.",
        "states": [
            {"name": "To Do", "group": "unstarted", "color": "#3A3A3A"},
            {"name": "In Progress", "group": "started", "color": "#F59E0B"},
            {"name": "Done", "group": "completed", "color": "#16A34A"},
        ],
        "transitions": {
            "To Do": ["In Progress"],
            "In Progress": ["To Do", "Done"],
            "Done": ["In Progress"],
        },
    },
}


class WorkflowError(Exception):
    pass


def is_workflow_enabled(project_id):
    return ProjectWorkflow.objects.filter(project_id=project_id, is_enabled=True).exists()


def is_project_admin(project_id, user_id):
    return ProjectMember.objects.filter(
        project_id=project_id, member_id=user_id, is_active=True, role=ADMIN_ROLE
    ).exists()


def check_transition(project_id, from_state_id, to_state_id, user_id):
    """Error message when the move is not allowed by the project's workflow, otherwise None."""
    if not from_state_id or not to_state_id or str(from_state_id) == str(to_state_id):
        return None
    if not is_workflow_enabled(project_id):
        return None
    rules = list(
        WorkflowTransition.objects.filter(
            project_id=project_id, from_state_id=from_state_id, to_state__deleted_at__isnull=True
        ).select_related("to_state")
    )
    if not rules:
        return None
    rule = next((rule for rule in rules if str(rule.to_state_id) == str(to_state_id)), None)
    from_name = State.all_state_objects.filter(pk=from_state_id).values_list("name", flat=True).first() or "this state"
    to_name = State.all_state_objects.filter(pk=to_state_id).values_list("name", flat=True).first() or "that state"
    if rule is None:
        allowed = ", ".join(rule.to_state.name for rule in sorted(rules, key=lambda r: r.to_state.sequence))
        return f"The workflow does not allow moving from {from_name} to {to_name}. Allowed: {allowed}."
    if rule.reviewer_ids and str(user_id) not in {str(reviewer) for reviewer in rule.reviewer_ids}:
        if not is_project_admin(project_id, user_id):
            return f"Only the reviewers of this step can move work items from {from_name} to {to_name}."
    return None


def serialize_workflow(project_id):
    workflow = ProjectWorkflow.objects.filter(project_id=project_id).first()
    transitions = WorkflowTransition.objects.filter(
        project_id=project_id, from_state__deleted_at__isnull=True, to_state__deleted_at__isnull=True
    ).order_by("created_at")
    return {
        "is_enabled": bool(workflow and workflow.is_enabled),
        "transitions": [
            {
                "id": str(transition.id),
                "from_state": str(transition.from_state_id),
                "to_state": str(transition.to_state_id),
                "reviewer_ids": [str(reviewer) for reviewer in transition.reviewer_ids],
            }
            for transition in transitions
        ],
        "templates": [
            {"key": key, "name": template["name"], "description": template["description"]}
            for key, template in WORKFLOW_TEMPLATES.items()
        ],
    }


def save_workflow(project, is_enabled, transitions, user_id):
    """Replace the workflow of the project. ``transitions`` is a list of {from_state, to_state, reviewer_ids}."""
    state_ids = {str(state_id) for state_id in State.objects.filter(project=project).values_list("id", flat=True)}
    member_ids = {
        str(member_id)
        for member_id in ProjectMember.objects.filter(project=project, is_active=True).values_list(
            "member_id", flat=True
        )
    }
    cleaned = {}
    for item in transitions or []:
        if not isinstance(item, dict):
            raise WorkflowError("Each transition needs a from_state and a to_state.")
        from_state, to_state = str(item.get("from_state") or ""), str(item.get("to_state") or "")
        if from_state not in state_ids or to_state not in state_ids:
            raise WorkflowError("Transitions can only use states of this project.")
        if from_state == to_state:
            continue
        reviewers = [str(reviewer) for reviewer in item.get("reviewer_ids") or []]
        if any(not is_valid_uuid(reviewer) or reviewer not in member_ids for reviewer in reviewers):
            raise WorkflowError("Reviewers must be members of this project.")
        cleaned[(from_state, to_state)] = sorted(set(reviewers))

    with transaction.atomic():
        workflow, _ = ProjectWorkflow.objects.get_or_create(
            project=project, defaults={"workspace_id": project.workspace_id, "created_by_id": user_id}
        )
        workflow.is_enabled = bool(is_enabled)
        workflow.updated_by_id = user_id
        workflow.save(update_fields=["is_enabled", "updated_by", "updated_at"])

        existing = {
            (str(transition.from_state_id), str(transition.to_state_id)): transition
            for transition in WorkflowTransition.objects.filter(project=project)
        }
        for key, transition in existing.items():
            if key not in cleaned:
                transition.delete(soft=False)
        for (from_state, to_state), reviewers in cleaned.items():
            transition = existing.get((from_state, to_state))
            if transition is None:
                WorkflowTransition.objects.create(
                    project=project,
                    workspace_id=project.workspace_id,
                    from_state_id=from_state,
                    to_state_id=to_state,
                    reviewer_ids=reviewers,
                    created_by_id=user_id,
                    updated_by_id=user_id,
                )
            elif sorted(map(str, transition.reviewer_ids)) != reviewers:
                transition.reviewer_ids = reviewers
                transition.updated_by_id = user_id
                transition.save(update_fields=["reviewer_ids", "updated_by", "updated_at"])
    return serialize_workflow(project.id)


def apply_template(project, template_key, user_id):
    """Create the template's missing states (matched by name) and use its transitions. Existing states are kept."""
    template = WORKFLOW_TEMPLATES.get(template_key)
    if template is None:
        raise WorkflowError("Unknown workflow template.")
    with transaction.atomic():
        states = {state.name.strip().lower(): state for state in State.objects.filter(project=project)}
        last_sequence = max([state.sequence for state in states.values()], default=0)
        for config in template["states"]:
            if config["name"].lower() in states:
                continue
            last_sequence += 15000
            states[config["name"].lower()] = State.objects.create(
                project=project,
                workspace_id=project.workspace_id,
                name=config["name"],
                group=config["group"],
                color=config["color"],
                sequence=last_sequence,
                created_by_id=user_id,
                updated_by_id=user_id,
            )
        transitions = [
            {"from_state": states[source.lower()].id, "to_state": states[target.lower()].id, "reviewer_ids": []}
            for source, targets in template["transitions"].items()
            for target in targets
        ]
        return save_workflow(project, True, transitions, user_id)
