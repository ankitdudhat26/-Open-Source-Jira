# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from typing import Any

# Django imports
from django.core.management import BaseCommand, CommandError

# Module imports
from plane.db.models import Project
from plane.utils.sow_descriptions import fill_sow_descriptions


class Command(BaseCommand):
    help = (
        "Write descriptions for the features and tasks of projects imported from a SOW. "
        "Descriptions someone has written or edited are kept."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, help="Only projects of this workspace (slug)")
        parser.add_argument("--project", type=str, help="Only this project (name)")

    def handle(self, *args: Any, **options: Any):
        projects = Project.objects.filter(project_issue__external_source="sow").distinct()
        if options.get("workspace"):
            projects = projects.filter(workspace__slug=options["workspace"])
        if options.get("project"):
            projects = projects.filter(name__iexact=options["project"])
        if not projects.exists():
            raise CommandError("No project with imported SOW work items found")

        for project in projects:
            updated = fill_sow_descriptions(project)
            self.stdout.write(f"  {project.workspace.slug} / {project.name}: {updated} work items updated")
        self.stdout.write(self.style.SUCCESS("Done"))
