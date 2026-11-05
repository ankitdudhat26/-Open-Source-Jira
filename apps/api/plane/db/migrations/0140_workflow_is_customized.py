# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Remembers which projects changed their workflow, and moves the others to the new default workflow.

A project whose workflow is still exactly the previous default (0138) follows the default: it gets the new one
(Backlog, To Do, In Progress, In QA, Waiting for Demo, Reopened, Done, Cancelled). States are matched by name ignoring
case, spaces and punctuation; missing ones are added and the eight are put in their categories. Work items keep their
states. Any other workflow was changed by hand: it is marked customized and kept as it is.
"""

from django.db import migrations, models

# frozen copies of plane.utils.workflow's default template, before and after
PREVIOUS_DEFAULT = {
    ("To Do", "In Progress"),
    ("In Progress", "In QA"),
    ("In QA", "Waiting for Demo"),
    ("In QA", "In Progress"),
    ("In QA", "To Do"),
    ("Waiting for Demo", "Done"),
    ("Waiting for Demo", "In Progress"),
    ("Waiting for Demo", "To Do"),
    ("Done", "Reopened"),
    ("Reopened", "In Progress"),
}
STATES = [
    {"name": "Backlog", "group": "backlog", "color": "#60646C"},
    {"name": "To Do", "group": "unstarted", "color": "#3A3A3A"},
    {"name": "In Progress", "group": "started", "color": "#F59E0B"},
    {"name": "In QA", "group": "started", "color": "#0EA5E9"},
    {"name": "Waiting for Demo", "group": "started", "color": "#8B5CF6"},
    {"name": "Reopened", "group": "started", "color": "#EF4444"},
    {"name": "Done", "group": "completed", "color": "#16A34A"},
    {"name": "Cancelled", "group": "cancelled", "color": "#9AA4BC"},
]
TRANSITIONS = {
    "Backlog": ["To Do", "Cancelled"],
    "To Do": ["In Progress", "Backlog", "Cancelled"],
    "In Progress": ["In QA", "To Do", "Cancelled"],
    "In QA": ["Waiting for Demo", "In Progress", "To Do", "Cancelled"],
    "Waiting for Demo": ["Done", "In Progress", "Cancelled"],
    "Reopened": ["In Progress", "To Do", "Cancelled"],
    "Done": ["Reopened"],
    "Cancelled": ["Backlog"],
}


def state_key(name):
    return "".join(character for character in name.lower() if character.isalnum())


def move_default_projects(apps, schema_editor):
    Project = apps.get_model("db", "Project")
    State = apps.get_model("db", "State")
    ProjectWorkflow = apps.get_model("db", "ProjectWorkflow")
    WorkflowTransition = apps.get_model("db", "WorkflowTransition")
    previous = {(state_key(source), state_key(target)) for source, target in PREVIOUS_DEFAULT}

    for project in Project.objects.filter(deleted_at__isnull=True).iterator():
        workflow = ProjectWorkflow.objects.filter(project_id=project.id, deleted_at__isnull=True).first()
        rules = WorkflowTransition.objects.filter(
            project_id=project.id,
            deleted_at__isnull=True,
            from_state__deleted_at__isnull=True,
            to_state__deleted_at__isnull=True,
        ).select_related("from_state", "to_state")
        current = {(state_key(rule.from_state.name), state_key(rule.to_state.name)) for rule in rules}
        if workflow is not None and current != previous:
            # changed by hand: keep it
            ProjectWorkflow.objects.filter(pk=workflow.pk).update(is_customized=True)
            continue

        states = {}
        project_states = (
            State.objects.filter(project_id=project.id, deleted_at__isnull=True).exclude(group="triage")
        ).order_by("sequence")
        for state in project_states:
            states.setdefault(state_key(state.name), state)
        sequence = max([state.sequence for state in states.values()], default=0)
        for config in STATES:
            state = states.get(state_key(config["name"]))
            if state is None:
                sequence += 15000
                states[state_key(config["name"])] = State.objects.create(
                    project_id=project.id,
                    workspace_id=project.workspace_id,
                    name=config["name"],
                    group=config["group"],
                    color=config["color"],
                    sequence=sequence,
                )
            elif state.group != config["group"]:
                State.objects.filter(pk=state.pk).update(group=config["group"])

        if workflow is None:
            workflow = ProjectWorkflow.objects.create(
                project_id=project.id, workspace_id=project.workspace_id, is_enabled=True
            )
        for rule in WorkflowTransition.objects.filter(project_id=project.id):
            rule.delete()
        WorkflowTransition.objects.bulk_create(
            [
                WorkflowTransition(
                    project_id=project.id,
                    workspace_id=project.workspace_id,
                    from_state_id=states[state_key(source)].id,
                    to_state_id=states[state_key(target)].id,
                    reviewer_ids=[],
                )
                for source, targets in TRANSITIONS.items()
                for target in targets
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0139_default_spreadsheet_layout"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectworkflow",
            name="is_customized",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(move_default_projects, migrations.RunPython.noop),
    ]
