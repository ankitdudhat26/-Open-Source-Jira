# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.db.models import Workspace
from plane.utils.jira.client import JiraError, parse_user_export
from plane.utils.user_migration_sheet import build_user_migration_sheet, jira_user_migration_rows


class Command(BaseCommand):
    help = "Write the user migration sheet (Excel) of a workspace — of every Jira user with --jira (read only)"

    def add_arguments(self, parser):
        parser.add_argument("workspace_slug", type=str)
        parser.add_argument("--jira", action="store_true", help="Every user of the connected Jira site, read live")
        parser.add_argument(
            "--users-file", type=str, help="The users CSV exported from admin.atlassian.com, for the hidden emails"
        )
        parser.add_argument(
            "--listed-only", action="store_true", help="Only the people of the users file (with --users-file)"
        )
        parser.add_argument("--output", "-o", type=str, help="The .xlsx file to write (default: the sheet's name)")

    def handle(self, *args, **options):
        workspace = Workspace.objects.filter(slug=options["workspace_slug"]).first()
        if workspace is None:
            raise CommandError("No such workspace.")
        rows = None
        if options["listed_only"] and not options["users_file"]:
            raise CommandError("--listed-only needs --users-file.")
        if options["jira"]:
            # imported here: the Jira views module loads the Celery task
            from plane.app.views.workspace.jira import client_for

            try:
                directory = {}
                if options["users_file"]:
                    with open(options["users_file"], encoding="utf-8-sig") as file:
                        directory = parse_user_export(file.read())
                rows = jira_user_migration_rows(
                    workspace,
                    client_for(workspace.slug),
                    progress=self.stdout.write,
                    directory=directory,
                    listed_only=options["listed_only"],
                )
            except JiraError as error:
                raise CommandError(str(error)) from error
        content, _, file_name = build_user_migration_sheet(workspace, rows)
        path = options["output"] or file_name
        with open(path, "wb") as file:
            file.write(content)
        self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
