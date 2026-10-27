# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations


def rename_bot_users(apps, schema_editor):
    """Workspace bot users created before the rebrand were called "Plane"."""
    User = apps.get_model("db", "User")
    User.objects.filter(is_bot=True, display_name="Plane").update(display_name="HLIS Flow")
    User.objects.filter(is_bot=True, first_name="Plane").update(first_name="HLIS Flow")


class Migration(migrations.Migration):
    dependencies = [("db", "0128_jira_import")]

    operations = [migrations.RunPython(rename_bot_users, migrations.RunPython.noop)]
