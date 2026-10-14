# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError

# Module imports
from plane.db.models import IssueType, ProjectIssueType

WORK_ITEM_TYPE_SOURCE = "plane"

# Feature -> Task -> Bug: a feature groups the tasks that build it, bugs are raised against a feature or task
WORK_ITEM_TYPES = [
    {
        "key": "feature",
        "name": "Feature",
        "description": "A feature from the SOW. Tasks and bugs are created under a feature.",
        "level": 1,
        "is_default": False,
        "color": "#8B5CF6",
    },
    {
        "key": "task",
        "name": "Task",
        "description": "A unit of work done to build a feature.",
        "level": 2,
        "is_default": True,
        "color": "#3B82F6",
    },
    {
        "key": "bug",
        "name": "Bug",
        "description": "A defect found in a feature or task.",
        "level": 2,
        "is_default": False,
        "color": "#EF4444",
    },
]


def ensure_project_work_item_types(project):
    """Make sure the Feature / Task / Bug work item types exist and are enabled for the project.

    Returns a dict of type key -> IssueType.
    """
    types = {}
    for config in WORK_ITEM_TYPES:
        issue_type = IssueType.objects.filter(
            workspace_id=project.workspace_id,
            external_source=WORK_ITEM_TYPE_SOURCE,
            external_id=config["key"],
        ).first()
        if issue_type is None:
            issue_type = IssueType.objects.create(
                workspace_id=project.workspace_id,
                name=config["name"],
                description=config["description"],
                level=config["level"],
                is_default=config["is_default"],
                logo_props={"in_use": "icon", "icon": {"color": config["color"]}},
                external_source=WORK_ITEM_TYPE_SOURCE,
                external_id=config["key"],
            )
        types[config["key"]] = issue_type

        if not ProjectIssueType.objects.filter(project_id=project.id, issue_type=issue_type).exists():
            try:
                ProjectIssueType.objects.create(
                    project_id=project.id,
                    workspace_id=project.workspace_id,
                    issue_type=issue_type,
                    level=config["level"],
                    is_default=config["is_default"],
                )
            except IntegrityError:
                pass
    return types


def serialize_work_item_types(types):
    return [
        {
            "id": str(types[config["key"]].id),
            "key": config["key"],
            "name": types[config["key"]].name,
            "description": types[config["key"]].description,
            "is_default": config["is_default"],
            "color": config["color"],
        }
        for config in WORK_ITEM_TYPES
    ]
