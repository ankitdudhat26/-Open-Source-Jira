# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Writes a parsed SOW (see plane.utils.sow_parser) into a project:

    Milestone (M1..)    -> Milestone (name, payment %, scope, amount) linked to the modules delivered in it
    Deliverable (D01..) -> Deliverable linked to its milestone
    Module (MOD01..)    -> Module
    Feature (F01..)     -> "Feature" work item in its module, tagged with its milestone
    Task (T001..)       -> "Task" work item under its feature, in the same module, tagged with its milestone,
                           labelled with its Task Type and Resource
    Resource (R01..)    -> label in the "Resource" label group (role, type and responsibilities)

Re-importing updates the records created by an earlier import (matched by their SOW ID) instead of duplicating them.
"""

# Python imports
import html

# Django imports
from django.db import transaction

# Module imports
from plane.db.models import (
    Deliverable,
    Issue,
    IssueLabel,
    IssueView,
    Label,
    Milestone,
    MilestoneModule,
    Module,
    ModuleIssue,
    ProjectResource,
    State,
)
from plane.utils.project_resources import is_assignable_member, sync_resource_assignees
from plane.utils.sow_descriptions import fill_sow_descriptions
from plane.utils.work_item_types import ensure_project_work_item_types

SOW_SOURCE = "sow"

TASK_TYPE_GROUP = "Task Type"
RESOURCE_GROUP = "Resource"
GROUP_COLORS = {TASK_TYPE_GROUP: "#0EA5E9", RESOURCE_GROUP: "#F59E0B"}

# Optional "Status" column of the task sheet -> state group
STATUS_TO_STATE_GROUP = {
    "not started": "unstarted",
    "to do": "unstarted",
    "todo": "unstarted",
    "planned": "unstarted",
    "in progress": "started",
    "wip": "started",
    "started": "started",
    "done": "completed",
    "completed": "completed",
    "complete": "completed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


def _description_html(text):
    if not text:
        return "<p></p>"
    return f"<p>{html.escape(text)}</p>"


def _match(model, project, code, name):
    """Find the record imported earlier for this SOW ID, else a manually added one with the same name."""
    record = model.objects.filter(project=project, external_source=SOW_SOURCE, external_id=code).first()
    if record is None and name:
        record = model.objects.filter(
            project=project,
            external_id__isnull=True,
            name__iexact=name,
        ).first()
    return record


def _resource_label_name(resource):
    return f"{resource['id']} · {resource['role']}"[:255]


def ensure_label(project, name, parent=None, description="", color=""):
    label = Label.objects.filter(project=project, name=name).first()
    if label is None:
        label = Label.objects.create(
            project=project,
            workspace_id=project.workspace_id,
            name=name,
            parent=parent,
            description=description,
            color=color,
            external_source=SOW_SOURCE,
        )
    else:
        changed = False
        if parent is not None and label.parent_id != parent.id:
            label.parent = parent
            changed = True
        if description and label.description != description:
            label.description = description
            changed = True
        if changed:
            label.save()
    return label


def build_summary(data):
    """Counts and the milestone -> module mapping that the import will create."""
    module_names = {row["id"]: row["name"] for row in data["modules"]}
    milestone_modules = _milestone_module_ids(data)
    return {
        "counts": {
            "milestones": len(data["milestones"]),
            "deliverables": len(data["deliverables"]),
            "resources": len(data["resources"]),
            "modules": len(data["modules"]),
            "features": len(data["features"]),
            "tasks": len(data["tasks"]),
        },
        "milestones": [
            {
                "id": row["id"],
                "name": row["name"],
                "payment_percentage": row["payment_percentage"],
                "amount": row["amount"],
                "scope": row["scope"],
                "modules": [
                    {"id": module_id, "name": module_names.get(module_id, module_id)}
                    for module_id in milestone_modules.get(row["id"], [])
                ],
                "deliverables": [d["id"] for d in data["deliverables"] if d["milestone_id"] == row["id"]],
                "feature_count": len([f for f in data["features"] if f["milestone_id"] == row["id"]]),
                "task_count": len([t for t in data["tasks"] if t["milestone_id"] == row["id"]]),
            }
            for row in data["milestones"]
        ],
        "deliverables": data["deliverables"],
        "resources": [
            {**row, "task_count": len([t for t in data["tasks"] if t["resource_id"] == row["id"]])}
            for row in data["resources"]
        ],
        "modules": [
            {
                **row,
                "feature_count": len([f for f in data["features"] if f["module_id"] == row["id"]]),
                "task_count": len([t for t in data["tasks"] if t["module_id"] == row["id"]]),
            }
            for row in data["modules"]
        ],
    }


def _milestone_module_ids(data):
    """A module belongs to every milestone in which one of its features or tasks is delivered."""
    module_order = [row["id"] for row in data["modules"]]
    mapping = {}
    for row in data["features"] + data["tasks"]:
        mapping.setdefault(row["milestone_id"], set()).add(row["module_id"])
    return {
        milestone_id: sorted(module_ids, key=lambda m: module_order.index(m) if m in module_order else 0)
        for milestone_id, module_ids in mapping.items()
    }


@transaction.atomic
def import_sow(project, data, resource_members=None, user=None):
    """resource_members: optional {resource ID: user id} chosen while reviewing the import."""
    types = ensure_project_work_item_types(project)

    # The SOW structure is built on modules, and is browsed through the views created below
    if not project.module_view or not project.issue_views_view:
        project.module_view = True
        project.issue_views_view = True
        project.save(update_fields=["module_view", "issue_views_view", "updated_at"])

    # Milestones
    milestones = {}
    for index, row in enumerate(data["milestones"]):
        milestone = _match(Milestone, project, row["id"], row["name"]) or Milestone(project=project)
        milestone.code = row["id"]
        milestone.name = row["name"]
        milestone.description = row["scope"]
        milestone.payment_percentage = row["payment_percentage"]
        if row["amount"] is not None:
            milestone.amount = row["amount"]
        milestone.sort_order = (index + 1) * 10000
        milestone.external_source = SOW_SOURCE
        milestone.external_id = row["id"]
        milestone.save()
        milestones[row["id"]] = milestone

    # Deliverables
    for index, row in enumerate(data["deliverables"]):
        deliverable = _match(Deliverable, project, row["id"], row["name"]) or Deliverable(project=project)
        deliverable.code = row["id"]
        deliverable.name = row["name"]
        deliverable.description = row["description"]
        deliverable.milestone = milestones[row["milestone_id"]]
        deliverable.sort_order = (index + 1) * 10000
        deliverable.external_source = SOW_SOURCE
        deliverable.external_id = row["id"]
        deliverable.save()

    # Modules
    modules = {}
    for index, row in enumerate(data["modules"]):
        module = _match(Module, project, row["id"], row["name"])
        if module is None:
            # Module names are unique per project
            module = Module.objects.filter(project=project, name__iexact=row["name"]).first() or Module(
                project=project
            )
        module.name = row["name"]
        module.description = row["scope"]
        module.external_source = SOW_SOURCE
        module.external_id = row["id"]
        module.save()
        # keep the SOW order (MOD01, MOD02, ...); Module.save puts a new module first
        sort_order = (index + 1) * 10000
        if module.sort_order != sort_order:
            Module.objects.filter(pk=module.pk).update(sort_order=sort_order)
            module.sort_order = sort_order
        modules[row["id"]] = module

    # Milestone <-> module links
    for milestone_code, module_codes in _milestone_module_ids(data).items():
        milestone = milestones[milestone_code]
        existing = set(
            MilestoneModule.objects.filter(milestone=milestone).values_list("module_id", flat=True)
        )
        MilestoneModule.objects.bulk_create(
            [
                MilestoneModule(
                    milestone=milestone,
                    module=modules[code],
                    project=project,
                    workspace_id=project.workspace_id,
                )
                for code in module_codes
                if modules[code].id not in existing
            ]
        )

    # Labels: Task Type and Resource groups
    task_type_group = ensure_label(project, TASK_TYPE_GROUP, color=GROUP_COLORS[TASK_TYPE_GROUP])
    resource_group = ensure_label(project, RESOURCE_GROUP, color=GROUP_COLORS[RESOURCE_GROUP])
    task_type_labels = {}
    for task_type in dict.fromkeys(row["task_type"] for row in data["tasks"]):
        task_type_labels[task_type] = ensure_label(
            project, task_type, parent=task_type_group, color=GROUP_COLORS[TASK_TYPE_GROUP]
        )
    resource_labels = {}
    resources = []
    for index, row in enumerate(data["resources"]):
        label = ensure_label(
            project,
            _resource_label_name(row),
            parent=resource_group,
            description=f"{row['resource_type']} — {row['responsibilities']}",
            color=GROUP_COLORS[RESOURCE_GROUP],
        )
        resource_labels[row["id"]] = label
        resource = ProjectResource.objects.filter(
            project=project, external_source=SOW_SOURCE, external_id=row["id"]
        ).first() or ProjectResource.objects.filter(
            project=project, external_id__isnull=True, role__iexact=row["role"]
        ).first() or ProjectResource(project=project)
        resource.code = row["id"]
        resource.role = row["role"][:255]
        resource.resource_type = row["resource_type"][:255]
        resource.responsibilities = row["responsibilities"]
        resource.label = label
        resource.sort_order = (index + 1) * 10000
        resource.external_source = SOW_SOURCE
        resource.external_id = row["id"]
        member_id = (resource_members or {}).get(row["id"])
        if member_id and is_assignable_member(project.id, member_id):
            resource.member_id = member_id
        resource.save()
        resources.append(resource)

    # Optional task status -> project state
    states_by_group = {}
    for state in State.objects.filter(project=project).order_by("sequence"):
        states_by_group.setdefault(state.group, state)

    # Features
    features = {}
    for row in data["features"]:
        feature = Issue.objects.filter(project=project, external_source=SOW_SOURCE, external_id=row["id"]).first()
        if feature is None:
            feature = Issue(project=project, external_source=SOW_SOURCE, external_id=row["id"])
        feature.name = row["name"][:255]
        # the full description is written by fill_sow_descriptions below; never overwrite one someone edited
        if feature._state.adding:
            feature.description_html = _description_html(row["details"])
        feature.type = types["feature"]
        feature.milestone = milestones[row["milestone_id"]]
        feature.parent = None
        feature.save()
        _set_module(feature, modules[row["module_id"]])
        features[row["id"]] = feature

    # Tasks
    for row in data["tasks"]:
        task = Issue.objects.filter(project=project, external_source=SOW_SOURCE, external_id=row["id"]).first()
        if task is None:
            task = Issue(project=project, external_source=SOW_SOURCE, external_id=row["id"])
        task.name = row["name"][:255]
        if task._state.adding:
            task.description_html = "<p></p>"
        task.type = types["task"]
        task.parent = features[row["feature_id"]]
        task.milestone = milestones[row["milestone_id"]]
        state_group = STATUS_TO_STATE_GROUP.get((row.get("status") or "").strip().lower())
        if state_group and state_group in states_by_group:
            task.state = states_by_group[state_group]
        task.save()
        _set_module(task, modules[row["module_id"]])
        _add_labels(task, [task_type_labels[row["task_type"]], resource_labels[row["resource_id"]]])

    if user is not None:
        _ensure_views(project, types, data, milestones, user)

    # Descriptions for the features and tasks that have none yet
    fill_sow_descriptions(project, feature_details={row["id"]: row["details"] for row in data["features"]})

    # Assign every task to the member who fills its resource
    for resource in resources:
        if resource.member_id:
            sync_resource_assignees(resource)

    return build_summary(data)


VIEW_DISPLAY_PROPERTIES = {
    "key": True,
    "issue_type": True,
    "state": True,
    "priority": True,
    "assignee": True,
    "due_date": True,
    "start_date": True,
    "labels": True,
    "modules": True,
    "sub_issue_count": True,
    "attachment_count": True,
    "link": True,
    "estimate": True,
    "created_on": False,
    "updated_on": False,
    "cycle": False,
}


def _ensure_views(project, types, data, milestones, user):
    """Saved views to browse the SOW: by type (features expand to their tasks) and one per milestone."""

    def type_filter(key):
        return {"and": [{"type_id__in": str(types[key].id)}]}

    views = [
        (
            "Features",
            "Features of the SOW by milestone. Expand a feature to see its tasks.",
            type_filter("feature"),
            {"layout": "list", "group_by": "milestone", "order_by": "sort_order", "sub_issue": False},
        ),
        (
            "Tasks",
            "All tasks, grouped by module.",
            type_filter("task"),
            {"layout": "list", "group_by": "module", "order_by": "sort_order", "sub_issue": True},
        ),
        (
            "Bugs",
            "All bugs, grouped by state.",
            type_filter("bug"),
            {"layout": "list", "group_by": "state", "order_by": "-created_at", "sub_issue": True},
        ),
    ]
    for row in data["milestones"]:
        milestone = milestones[row["id"]]
        views.append(
            (
                f"{row['id']} · {row['name']}"[:255],
                f"Work delivered in milestone {row['id']}, grouped by module.",
                {"and": [{"milestone_id__in": str(milestone.id)}]},
                {"layout": "list", "group_by": "module", "order_by": "sort_order", "sub_issue": True},
            )
        )

    for name, description, rich_filters, display_filters in views:
        view = IssueView.objects.filter(project=project, name=name).first() or IssueView(
            project=project, workspace_id=project.workspace_id, name=name, owned_by=user, access=1
        )
        view.description = description
        view.rich_filters = rich_filters
        view.display_filters = {"show_empty_groups": False, "calendar_date_range": "", "type": None, **display_filters}
        view.display_properties = VIEW_DISPLAY_PROPERTIES
        view.save()


def _set_module(issue, module):
    if not ModuleIssue.objects.filter(issue=issue, module=module).exists():
        ModuleIssue.objects.create(issue=issue, module=module, project_id=issue.project_id)


def _add_labels(issue, labels):
    existing = set(IssueLabel.objects.filter(issue=issue).values_list("label_id", flat=True))
    IssueLabel.objects.bulk_create(
        [
            IssueLabel(issue=issue, label=label, project_id=issue.project_id, workspace_id=issue.workspace_id)
            for label in labels
            if label.id not in existing
        ],
        ignore_conflicts=True,
    )
