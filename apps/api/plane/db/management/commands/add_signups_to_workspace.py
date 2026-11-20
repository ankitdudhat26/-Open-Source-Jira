# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.authentication.utils.workspace_project_join import default_workspace, join_default_workspace
from plane.db.models import User, Workspace, WorkspaceMember


class Command(BaseCommand):
    help = (
        "Add the people who signed up with the app link (no invite) to the organization's workspace as Clients. "
        "Lists them only, unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            type=str,
            help="Workspace slug (default: DEFAULT_WORKSPACE_SLUG, else the one most people are in)",
        )
        parser.add_argument(
            "--without-workspace-only",
            action="store_true",
            help="Only people in no workspace at all (not the ones who made a workspace of their own)",
        )
        parser.add_argument("--apply", action="store_true", help="Add them (otherwise only list them)")

    def handle(self, *args, **options):
        workspace = (
            Workspace.objects.filter(slug=options["workspace"]).first() if options["workspace"] else default_workspace()
        )
        if workspace is None:
            raise CommandError("No such workspace.")
        # removed members keep a deactivated membership: they are not added back
        people = User.objects.filter(is_bot=False, is_active=True).exclude(
            id__in=WorkspaceMember.objects.filter(workspace=workspace).values("member_id")
        )
        if options["without_workspace_only"]:
            people = people.exclude(id__in=WorkspaceMember.objects.values("member_id"))
        people = list(people.order_by("date_joined"))
        for user in people:
            other = list(
                WorkspaceMember.objects.filter(member=user, is_active=True).values_list("workspace__slug", flat=True)
            )
            self.stdout.write(f"{user.email or user.display_name}  {'(in ' + ', '.join(other) + ')' if other else ''}")
            if options["apply"]:
                join_default_workspace(user, workspace=workspace)
        verb = "Added" if options["apply"] else "Would add (run with --apply)"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(people)} people to {workspace.slug} as Clients"))
