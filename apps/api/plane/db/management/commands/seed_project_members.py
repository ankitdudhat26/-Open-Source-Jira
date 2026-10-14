# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from typing import Any

# Django imports
from django.core.management import BaseCommand, CommandError
from django.db import transaction

# Module imports
from plane.db.models import (
    Profile,
    Project,
    ProjectMember,
    ProjectResource,
    ProjectUserProperty,
    User,
    WorkspaceMember,
)
from plane.utils.project_resources import sync_resource_assignees

MEMBER_ROLE = 15

# One demo member per role of the SOW template (resource type -> member)
SEED_MEMBERS = [
    {"first_name": "Priya", "last_name": "Shah", "resource_type": "Designer"},
    {"first_name": "Rahul", "last_name": "Mehta", "resource_type": "Flutter Dev"},
    {"first_name": "Karan", "last_name": "Patel", "resource_type": "Full Stack Dev"},
    {"first_name": "Neha", "last_name": "Joshi", "resource_type": "Full Stack Dev"},
    {"first_name": "Vikram", "last_name": "Rao", "resource_type": "QA"},
]


class Command(BaseCommand):
    help = (
        "Add demo team members to a project so they can be mapped to its resources. "
        "Members are created without a password; set one with `reset_password` to log in as them."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, required=True, help="Workspace slug")
        parser.add_argument("--project", type=str, required=True, help="Project ID or name")
        parser.add_argument("--email-domain", type=str, default="example.com", help="Domain of the seed emails")
        parser.add_argument(
            "--map-resources",
            action="store_true",
            help="Also map each resource that has no member to a seed member of the same resource type "
            "and assign its tasks",
        )

    def handle(self, *args: Any, **options: Any):
        project = (
            Project.objects.filter(workspace__slug=options["workspace"], id=options["project"]).first()
            if self._is_uuid(options["project"])
            else Project.objects.filter(workspace__slug=options["workspace"], name__iexact=options["project"]).first()
        )
        if project is None:
            raise CommandError("Project not found in that workspace")

        with transaction.atomic():
            members = [self._ensure_member(project, seed, options["email_domain"]) for seed in SEED_MEMBERS]
            if options["map_resources"]:
                self._map_resources(project, members)

        for user, seed in members:
            self.stdout.write(f"  {user.display_name:<14} {user.email:<28} {seed['resource_type']}")
        self.stdout.write(self.style.SUCCESS(f"{len(members)} members are in project {project.name}"))

    @staticmethod
    def _is_uuid(value):
        import uuid

        try:
            uuid.UUID(str(value))
            return True
        except ValueError:
            return False

    def _ensure_member(self, project, seed, email_domain):
        email = f"{seed['first_name']}.{seed['last_name']}@{email_domain}".lower()
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User(
                email=email,
                username=email.split("@")[0].replace(".", "_"),
                first_name=seed["first_name"],
                last_name=seed["last_name"],
                display_name=f"{seed['first_name']} {seed['last_name']}",
                is_active=True,
                is_password_autoset=True,
            )
            user.set_unusable_password()
            user.save()
        Profile.objects.get_or_create(user=user)

        workspace_member, _ = WorkspaceMember.objects.get_or_create(
            workspace_id=project.workspace_id, member=user, defaults={"role": MEMBER_ROLE}
        )
        if not workspace_member.is_active:
            workspace_member.is_active = True
            workspace_member.save(update_fields=["is_active"])

        project_member = ProjectMember.objects.filter(project=project, member=user).first()
        if project_member is None:
            ProjectMember.objects.create(project=project, member=user, role=MEMBER_ROLE)
        elif not project_member.is_active:
            project_member.is_active = True
            project_member.save(update_fields=["is_active"])
        ProjectUserProperty.objects.get_or_create(user=user, project=project)
        return user, seed

    def _map_resources(self, project, members):
        available = list(members)
        for resource in ProjectResource.objects.filter(project=project, member__isnull=True):
            match = next((m for m in available if m[1]["resource_type"].lower() == resource.resource_type.lower()), None)
            if match is None:
                continue
            available.remove(match)
            resource.member = match[0]
            resource.save(update_fields=["member", "updated_at"])
            assigned = sync_resource_assignees(resource)
            self.stdout.write(f"  mapped {resource.code} {resource.role} -> {match[0].display_name} ({assigned} tasks)")
