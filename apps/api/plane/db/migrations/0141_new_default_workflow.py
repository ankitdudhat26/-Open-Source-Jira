# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Every project moves to the new default workflow: To Do → In Progress → In QA → Done, with Reopen.

The same steps as plane.utils.workflow.adopt_default_workflow (frozen here), for every project, also the customized
ones and the ones cloned from Jira:

* the five statuses, in order and category, and only them;
* every other status is merged into the one it stands for, with its work items: by name first ("IN QA", "Todo",
  "Reopened", "Resolved" → In QA, "QA Failed" → Reopen, "in production" → Done…), else by category (Backlog / not
  started → To Do, started → In Progress, completed and cancelled → Done); then it is deleted (soft);
* To Do is where new work items start, the old rules are replaced by the new ones and the workflow is enforced.
"""

from django.db import migrations, models
from django.utils import timezone
from django.utils.text import slugify

STATES = [
    {"name": "To Do", "group": "unstarted", "color": "#60646C"},
    {"name": "In Progress", "group": "started", "color": "#2563EB"},
    {"name": "In QA", "group": "started", "color": "#7C3AED"},
    {"name": "Reopen", "group": "started", "color": "#EA580C"},
    {"name": "Done", "group": "completed", "color": "#16A34A"},
]
TRANSITIONS = {
    "To Do": ["In Progress"],
    "In Progress": ["To Do", "In QA"],
    "In QA": ["In Progress", "Reopen", "Done"],
    "Reopen": ["In Progress", "To Do"],
    "Done": ["Reopen", "In QA"],
}
ALIASES = {
    "To Do": {"todo", "open"},
    "In Progress": {"inprogress"},
    "In QA": {"inqa", "qa", "testingqa"},
    "Reopen": {"reopen", "reopened"},
    "Done": {"done"},
}
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


def state_key(name):
    return "".join(character for character in name.lower() if character.isalnum())


def default_name_for(name):
    key = state_key(name)
    return next((default for default, keys in ALIASES.items() if key in keys), None)


def default_status_for(name, group):
    alias = default_name_for(name)
    if alias:
        return alias
    lowered = name.lower()
    if group == "started":
        for target, words in MOVE_BY_WORDS:
            if any(word in lowered for word in words):
                return target
    elif any(word in lowered for word in MOVE_BY_WORDS[0][1]):
        return "Reopen"
    return MOVE_BY_GROUP.get(group, "To Do")


def adopt(apps, project, now):
    State = apps.get_model("db", "State")
    Issue = apps.get_model("db", "Issue")
    DraftIssue = apps.get_model("db", "DraftIssue")
    Project = apps.get_model("db", "Project")
    ProjectWorkflow = apps.get_model("db", "ProjectWorkflow")
    WorkflowTransition = apps.get_model("db", "WorkflowTransition")

    states = list(
        State._base_manager.filter(project_id=project.id, deleted_at__isnull=True)
        .exclude(group="triage")
        .order_by("sequence", "created_at")
    )
    defaults, merged = {}, []
    for index, config in enumerate(STATES):
        matches = [state for state in states if default_name_for(state.name) == config["name"]]
        exact = [state for state in matches if state_key(state.name) == state_key(config["name"])]
        primary = (exact or matches or [None])[0]
        for duplicate in matches:
            if duplicate is not primary:
                Issue._base_manager.filter(state_id=duplicate.id).update(state_id=primary.id)
                DraftIssue._base_manager.filter(state_id=duplicate.id).update(state_id=primary.id)
                merged.append(duplicate.id)
        if merged:
            State._base_manager.filter(pk__in=merged).update(deleted_at=now, default=False)
        values = {
            "name": config["name"],
            "group": config["group"],
            "color": config["color"],
            "sequence": (index + 1) * 15000,
            "default": config["name"] == "To Do",
            "slug": slugify(config["name"]),
        }
        if primary is None:
            primary = State._base_manager.create(project_id=project.id, workspace_id=project.workspace_id, **values)
        else:
            State._base_manager.filter(pk=primary.pk).update(**values)
        defaults[config["name"]] = primary

    default_ids = {state.id for state in defaults.values()}
    others = [state for state in states if state.id not in merged and state.id not in default_ids]
    for state in others:
        target = defaults[default_status_for(state.name, state.group)]
        Issue._base_manager.filter(state_id=state.id).update(state_id=target.id)
        DraftIssue._base_manager.filter(state_id=state.id).update(state_id=target.id)
    if others:
        State._base_manager.filter(pk__in=[state.id for state in others]).update(deleted_at=now, default=False)
    Project._base_manager.filter(pk=project.id).update(default_state_id=defaults["To Do"].id)

    WorkflowTransition._base_manager.filter(project_id=project.id).delete()
    rules = [(defaults[source], defaults[target]) for source, targets in TRANSITIONS.items() for target in targets]
    WorkflowTransition._base_manager.bulk_create(
        [
            WorkflowTransition(
                project_id=project.id,
                workspace_id=project.workspace_id,
                from_state_id=source.id,
                to_state_id=target.id,
                reviewer_ids=[],
            )
            for source, target in rules
        ]
    )
    workflow = ProjectWorkflow._base_manager.filter(project_id=project.id, deleted_at__isnull=True).first()
    if workflow is None:
        workflow = ProjectWorkflow._base_manager.create(project_id=project.id, workspace_id=project.workspace_id)
    ProjectWorkflow._base_manager.filter(pk=workflow.pk).update(
        is_enabled=True, is_customized=False, legacy_state_ids=[]
    )


def adopt_all(apps, schema_editor):
    Project = apps.get_model("db", "Project")
    now = timezone.now()
    for project in Project._base_manager.filter(deleted_at__isnull=True).iterator():
        adopt(apps, project, now)


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0140_workflow_is_customized"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectworkflow",
            name="legacy_state_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(adopt_all, migrations.RunPython.noop),
    ]
