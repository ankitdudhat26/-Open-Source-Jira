# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The project members emailed when a client sends a request on the Intake link (nobody until switched on)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0141_new_default_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="intakeform",
            name="notify_member_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
