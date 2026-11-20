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
from django.utils import timezone
from django.utils.text import slugify

from plane.db.models import (
    DraftIssue,
    Issue,
    Project,
    ProjectMember,
    ProjectWorkflow,
    State,
    WorkflowTransition,
)
from plane.utils.uuid import is_valid_uuid

ADMIN_ROLE = 20

DEFAULT_TEMPLATE = "default"

# The workflow every project follows (existing, new and cloned from Jira); a project can change it in its settings.
DEFAULT_STATES = [
    {"name": "To Do", "group": "unstarted", "color": "#60646C"},
    {"name": "In Progress", "group": "started", "color": "#2563EB"},
    {"name": "In QA", "group": "started", "color": "#7C3AED"},
    {"name": "Reopen", "group": "started", "color": "#EA580C"},
    {"name": "Done", "group": "completed", "color": "#16A34A"},
]
DEFAULT_TRANSITIONS = {
    "To Do": ["In Progress"],  # start work
    "In Progress": ["To Do", "In QA"],  # back to the queue / development completed
    "In QA": ["In Progress", "Reopen", "Done"],  # direct fixes / QA failed / QA passed
    "Reopen": ["In Progress", "To Do"],  # restart development / return to the backlog
    "Done": ["Reopen", "In QA"],  # issue found after completion / retesting
}
# other names of the default statuses: their work items move into the default status, which keeps its name
STATE_ALIASES = {
    "To Do": {"todo", "open"},
    "In Progress": {"inprogress"},
    "In QA": {"inqa", "qa", "testingqa"},
    "Reopen": {"reopen", "reopened"},
    "Done": {"done"},
}
# every other status of the old workflows goes into one of the five, by what its name says, else by its category
MOVE_BY_WORDS = [
    ("Reopen", ("reopen", "fail", "rework")),
    ("Done", ("production", "deployed", "deploy", "live")),
    ("In QA", ("qa", "test", "review", "resolved", "demo", "uat", "verif", "approval", "done")),
]
MOVE_BY_GROUP = {
    "backlog": "To Do",
    "unstarted": "To Do",
    "started": "In Progress",
    "completed": "Done",
    "cancelled": "Done",
}


WORKFLOW_TEMPLATES = {
    DEFAULT_TEMPLATE: {
        "name": "Default",
        "description": (
            "To Do → In Progress → In QA → Done. QA failed goes to Reopen and back to In Progress; Done can be "
            "Reopened or sent back to QA."
        ),
        "states": DEFAULT_STATES,
        "transitions": DEFAULT_TRANSITIONS,
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
        # false while the project follows the default workflow (and gets its updates)
        "is_customized": bool(workflow and workflow.is_customized),
        "default_template": DEFAULT_TEMPLATE,
        # statuses left by the old workflow with work items in them: they only lead into the new flow
        "legacy_state_ids": [
            str(state_id)
            for state_id in State.objects.filter(
                project_id=project_id, pk__in=(workflow.legacy_state_ids if workflow else []) or []
            ).values_list("id", flat=True)
        ],
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


def mark_customized(project_id):
    """The project's states or workflow were changed by hand: later changes to the default leave it alone."""
    ProjectWorkflow.objects.filter(project_id=project_id, is_customized=False).update(is_customized=True)


def save_workflow(project, is_enabled, transitions, user_id, is_customized=True):
    """Replace the workflow of the project. ``transitions`` is a list of {from_state, to_state, reviewer_ids}.
    A workflow saved from the project's settings is customized; applying the default template is not."""
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
        workflow.is_customized = bool(is_customized)
        workflow.updated_by_id = user_id
        workflow.save(update_fields=["is_enabled", "is_customized", "updated_by", "updated_at"])

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


def state_key(name):
    """A state name for matching: "Todo", "To Do" and "TO-DO" are one state, so are "IN QA" and "In QA"."""
    return "".join(character for character in name.lower() if character.isalnum())


def default_name_for(name):
    """The default status a status name stands for ("IN QA", "Reopened", "Todo"…), or None."""
    key = state_key(name)
    return next((default for default, keys in STATE_ALIASES.items() if key in keys), None)


def default_status_for(name, group):
    """The default status a status of another workflow becomes ("Closed" → Done, "Resolved" → In QA…)."""
    alias = default_name_for(name)
    if alias:
        return alias
    lowered = name.lower()
    # a started status is placed by its name ("Testing Done in Dev" → In QA); others by their category
    if group == "started":
        for target, words in MOVE_BY_WORDS:
            if any(word in lowered for word in words):
                return target
    elif any(word in lowered for word in MOVE_BY_WORDS[0][1]):
        return "Reopen"
    return MOVE_BY_GROUP.get(group, "To Do")


def apply_default_workflow(project, user_id=None):
    """The default workflow for a project that has none yet (a new project)."""
    if ProjectWorkflow.objects.filter(project=project).exists():
        return None
    return adopt_default_workflow(project, user_id)


def ensure_default_workflow(project, user_id=None):
    """After an import or sync from Jira: the default workflow, unless the project's own was set in its settings."""
    if ProjectWorkflow.objects.filter(project=project, is_customized=True).exists():
        return None
    return adopt_default_workflow(project, user_id)


def adopt_default_workflow(project, user_id=None):
    """Make the project follow the default workflow (the same steps as the 0141 migration):

    * the five default statuses, in this order and category; a status with another name for one of them ("IN QA",
      "Reopened", "Todo", "Open"…) is merged into it, with its work items;
    * every other status is merged into the default one it stands for (by its name, else its category: "Closed" →
      Done, "Resolved" → In QA, "Backlog" → To Do…), with its work items, and removed;
    * To Do is where new work items start; the rules are the default ones; the project follows the default again.
    """
    now = timezone.now()
    with transaction.atomic():
        states = list(State.objects.filter(project=project).exclude(group="triage").order_by("sequence", "created_at"))
        defaults = {}
        merged = []
        for index, config in enumerate(DEFAULT_STATES):
            matches = [state for state in states if default_name_for(state.name) == config["name"]]
            exact = [state for state in matches if state_key(state.name) == state_key(config["name"])]
            primary = (exact or matches or [None])[0]
            # the other names for it: their work items move into it
            for duplicate in matches:
                if duplicate is not primary:
                    Issue.all_objects.filter(state=duplicate).update(state=primary)
                    DraftIssue.all_objects.filter(state=duplicate).update(state=primary)
                    merged.append(duplicate.id)
            if merged:
                State.objects.filter(pk__in=merged).update(deleted_at=now, default=False)
            values = {
                "name": config["name"],
                "group": config["group"],
                "color": config["color"],
                "sequence": (index + 1) * 15000,
                "default": config["name"] == "To Do",
                "slug": slugify(config["name"]),
            }
            if primary is None:
                primary = State.objects.create(
                    project=project,
                    workspace_id=project.workspace_id,
                    created_by_id=user_id,
                    updated_by_id=user_id,
                    **values,
                )
            # saving a new state puts it last: the order (and the slug of a renamed one) is set here
            State.objects.filter(pk=primary.pk).update(**values)
            defaults[config["name"]] = primary

        # every other status is merged into the one it stands for, with its work items, and removed
        others = [
            state
            for state in states
            if state.id not in merged and all(state.id != default.id for default in defaults.values())
        ]
        for state in others:
            target = defaults[default_status_for(state.name, state.group)]
            Issue.all_objects.filter(state=state).update(state=target)
            DraftIssue.all_objects.filter(state=state).update(state=target)
        if others:
            State.objects.filter(pk__in=[state.id for state in others]).update(deleted_at=now, default=False)
        Project.objects.filter(pk=project.pk).update(default_state=defaults["To Do"])

        WorkflowTransition.all_objects.filter(project=project).delete()
        rules = [
            (defaults[source], defaults[target])
            for source, targets in DEFAULT_TRANSITIONS.items()
            for target in targets
        ]
        WorkflowTransition.objects.bulk_create(
            [
                WorkflowTransition(
                    project=project,
                    workspace_id=project.workspace_id,
                    from_state_id=source.id,
                    to_state_id=target.id,
                    reviewer_ids=[],
                    created_by_id=user_id,
                    updated_by_id=user_id,
                )
                for source, target in rules
            ]
        )
        workflow, _ = ProjectWorkflow.objects.get_or_create(
            project=project, defaults={"workspace_id": project.workspace_id, "created_by_id": user_id}
        )
        workflow.is_enabled = True
        workflow.is_customized = False
        workflow.legacy_state_ids = []
        workflow.updated_by_id = user_id
        workflow.save(update_fields=["is_enabled", "is_customized", "legacy_state_ids", "updated_by", "updated_at"])
    return serialize_workflow(project.id)


def apply_template(project, template_key, user_id):
    """Reset the project to a ready-made workflow (only the default one now)."""
    if template_key not in WORKFLOW_TEMPLATES:
        raise WorkflowError("Unknown workflow template.")
    return adopt_default_workflow(project, user_id)
