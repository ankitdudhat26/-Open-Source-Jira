# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Projects imported from Jira were created with Sprints, Modules, Views and Intake off. Turn them on, as for a project
created in the app (the Intake request link stays off until a project admin turns it on)."""

from django.db import migrations

FEATURES = ("cycle_view", "module_view", "issue_views_view", "page_view", "intake_view")


def enable_features(apps, schema_editor):
    Project = apps.get_model("db", "Project")
    Intake = apps.get_model("db", "Intake")
    JiraEntityMap = apps.get_model("db", "JiraEntityMap")

    project_ids = JiraEntityMap.objects.filter(entity_type="project", plane_id__isnull=False).values_list(
        "plane_id", flat=True
    )
    projects = Project.objects.filter(id__in=list(project_ids), deleted_at__isnull=True)
    projects.update(**{feature: True for feature in FEATURES})
    for project in projects:
        if not Intake.objects.filter(project=project, is_default=True, deleted_at__isnull=True).exists():
            Intake.objects.create(
                name=f"{project.name} Intake", project=project, workspace_id=project.workspace_id, is_default=True
            )


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0134_intake_form"),
    ]

    operations = [migrations.RunPython(enable_features, migrations.RunPython.noop)]
