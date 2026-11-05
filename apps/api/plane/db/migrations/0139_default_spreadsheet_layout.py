# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project work items open as a spreadsheet by default (see plane.db.models.issue.get_default_display_filters).

People whose view settings of a project were created for them (when they joined) and never changed still have the
old default, the list: switch those to the spreadsheet. A layout someone picked (the row changed after it was
created) is kept.
"""

from datetime import timedelta

from django.db import migrations
from django.db.models import F


def use_spreadsheet_for_untouched_views(apps, schema_editor):
    ProjectUserProperty = apps.get_model("db", "ProjectUserProperty")
    untouched = ProjectUserProperty.objects.filter(
        updated_at__lte=F("created_at") + timedelta(seconds=2), display_filters__layout="list"
    )
    for view in untouched.iterator():
        view.display_filters = {**view.display_filters, "layout": "spreadsheet"}
        # keep updated_at as it was: the person still has not picked a layout
        ProjectUserProperty.objects.filter(pk=view.pk).update(display_filters=view.display_filters)


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0138_default_workflow"),
    ]

    operations = [
        migrations.RunPython(use_spreadsheet_for_untouched_views, migrations.RunPython.noop),
    ]
