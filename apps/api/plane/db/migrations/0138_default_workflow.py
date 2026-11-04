# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Gives every existing project without a workflow the default one (new projects get it when they are created).

States are matched by name ignoring case, spaces and punctuation ("IN QA" is "In QA", "Todo" is "To Do"), so
Jira cloned projects keep their states and work items; missing states are added. Other states are left alone and,
having no rules, stay unrestricted. A project that already has a workflow keeps it.
"""

from django.db import migrations

# frozen copy of plane.utils.workflow's "default" template
STATES = [
    {"name": "To Do", "group": "unstarted", "color": "#3A3A3A"},
    {"name": "In Progress", "group": "started", "color": "#F59E0B"},
    {"name": "In QA", "group": "started", "color": "#0EA5E9"},
    {"name": "Waiting for Demo", "group": "started", "color": "#8B5CF6"},
    {"name": "Done", "group": "completed", "color": "#16A34A"},
    {"name": "Reopened", "group": "started", "color": "#EF4444"},
]
TRANSITIONS = {
    "To Do": ["In Progress"],
    "In Progress": ["In QA"],
    "In QA": ["Waiting for Demo", "In Progress", "To Do"],
    "Waiting for Demo": ["Done", "In Progress", "To Do"],
    "Done": ["Reopened"],
    "Reopened": ["In Progress"],
}


def state_key(name):
    return "".join(character for character in name.lower() if character.isalnum())


def apply_default_workflow(apps, schema_editor):
    Project = apps.get_model("db", "Project")
    State = apps.get_model("db", "State")
    ProjectWorkflow = apps.get_model("db", "ProjectWorkflow")
    WorkflowTransition = apps.get_model("db", "WorkflowTransition")

    with_workflow = set(ProjectWorkflow.objects.filter(deleted_at__isnull=True).values_list("project_id", flat=True))
    for project in Project.objects.filter(deleted_at__isnull=True).exclude(id__in=with_workflow).iterator():
        states = {}
        project_states = (
            State.objects.filter(project_id=project.id, deleted_at__isnull=True).exclude(group="triage")
        ).order_by("sequence")
        for state in project_states:
            states.setdefault(state_key(state.name), state)
        sequence = max([state.sequence for state in states.values()], default=0)
        for config in STATES:
            if state_key(config["name"]) in states:
                continue
            sequence += 15000
            states[state_key(config["name"])] = State.objects.create(
                project_id=project.id,
                workspace_id=project.workspace_id,
                name=config["name"],
                group=config["group"],
                color=config["color"],
                sequence=sequence,
                default=not project_states.filter(default=True).exists() and config["name"] == "To Do",
            )
        ProjectWorkflow.objects.create(project_id=project.id, workspace_id=project.workspace_id, is_enabled=True)
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
        ("db", "0137_workspace_access_control"),
    ]

    operations = [
        migrations.RunPython(apply_default_workflow, migrations.RunPython.noop),
    ]
