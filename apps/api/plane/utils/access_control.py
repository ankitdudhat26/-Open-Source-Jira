# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Role-wise access to the workspace's features, set by its admins in Settings → Roles & access.

Every feature has actions (view, create, edit, delete). For each role — Sub Admin, Member, Client — an admin can allow
or deny an action, and override that for one person (custom access). A cell left alone keeps the built-in rule of the
code. The rules of a person's workspace role apply in every project — new or cloned from Jira — whatever their project
role: being a project admin does not lift them. Workspace admins always have full access, and so do Sub Admins in the
projects they created. A project role can only lower the rules (a Member who is a client in a project gets the client
rules there). For clients only what an admin set applies; the code keeps their read-only rules.

A request is matched to a feature by its URL and to an action by its method: a denied action is refused for every
endpoint of the feature (`enforce`), and an allowed one passes the role checks that would refuse it (`is_granted`)."""

import re

from plane.db.models import ProjectMember, WorkspaceAccessPolicy, WorkspaceMember

ACTIONS = ("view", "create", "edit", "delete")
ROLES = ("sub_admin", "member", "client")
ROLE_LABELS = {"admin": "Admin", "sub_admin": "Sub Admin", "member": "Member", "client": "Client"}
ADMIN, MEMBER, CLIENT = 20, 15, 5

# key, label, description, where it lives, the actions that can be set, and the URL segments that belong to it.
# Viewing project settings, project members and workspace members is not settable: the work item screens need
# the states, labels and people to show anything.
FEATURES = [
    {
        "key": "work_items",
        "label": "Work items",
        "description": "Work items, their properties, attachments and links",
        "scope": "project",
        "actions": ACTIONS,
        "segments": (
            "issues",
            "work-items",
            "issues-detail",
            "issue-dates",
            "bulk-delete-issues",
            "bulk-archive-issues",
            "archived-issues",
            "deleted-issues",
            "work-item-tree",
        ),
        "action_labels": {
            "view": "See work items and open them",
            "create": "Add new work items",
            "edit": "Change work items: title, state, assignees, dates…",
            "delete": "Delete work items",
        },
    },
    {
        "key": "comments",
        "label": "Comments",
        "description": "Comments and reactions on work items",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("comments",),
        "action_labels": {
            "view": "Read comments on work items",
            "create": "Write comments and react",
            "edit": "Edit comments",
            "delete": "Delete comments",
        },
    },
    {
        "key": "sprints",
        "label": "Sprints",
        "description": "Sprints and their work items",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("cycles", "archived-cycles"),
        "action_labels": {
            "view": "See Sprints in the project sidebar",
            "create": "Create sprints",
            "edit": "Change sprints and add work items to them",
            "delete": "Delete sprints",
        },
    },
    {
        "key": "modules",
        "label": "Modules",
        "description": "Modules and their work items",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("modules", "archived-modules"),
        "action_labels": {
            "view": "See Modules in the project sidebar",
            "create": "Create modules",
            "edit": "Change modules and add work items to them",
            "delete": "Delete modules",
        },
    },
    {
        "key": "views",
        "label": "Views",
        "description": "Saved views of work items",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("views", "project-views"),
        "action_labels": {
            "view": "See Views in the project sidebar",
            "create": "Save new views",
            "edit": "Change saved views",
            "delete": "Delete saved views",
        },
    },
    {
        "key": "pages",
        "label": "Pages",
        "description": "Project pages",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("pages", "pages-summary"),
        "action_labels": {
            "view": "See Pages in the project sidebar",
            "create": "Create pages",
            "edit": "Edit pages",
            "delete": "Delete pages",
        },
    },
    {
        "key": "intake",
        "label": "Intake",
        "description": "Requests in Intake: accept, decline and snooze them",
        "scope": "project",
        "actions": ACTIONS,
        "segments": (
            "intakes",
            "intake-issues",
            "inbox-issues",
            "inboxes",
            "intake-work-items",
            "intake-state",
        ),
        "action_labels": {
            "view": "See Intake in the project sidebar",
            "create": "Add requests to Intake",
            "edit": "Accept, decline or snooze requests",
            "delete": "Delete requests",
        },
    },
    {
        "key": "milestones",
        "label": "Milestones",
        "description": "Milestones, payments and the SOW import",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("milestones", "sow-import"),
        "action_labels": {
            "view": "See Milestones in the project sidebar",
            "create": "Add milestones or import a SOW",
            "edit": "Change milestones and payments",
            "delete": "Delete milestones",
        },
    },
    {
        "key": "resources",
        "label": "Resources",
        "description": "The people filling each role of the project",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("resources",),
        "action_labels": {
            "view": "See Resources in the project sidebar",
            "create": "Add resources",
            "edit": "Change resources and who fills them",
            "delete": "Delete resources",
        },
    },
    {
        "key": "deliverables",
        "label": "Deliverables",
        "description": "Deliverables of the milestones",
        "scope": "project",
        "actions": ACTIONS,
        "segments": ("deliverables",),
        "action_labels": {
            "view": "See deliverables",
            "create": "Add deliverables",
            "edit": "Change deliverables",
            "delete": "Delete deliverables",
        },
    },
    {
        "key": "project_settings",
        "label": "Project settings",
        "description": "States, labels, estimates, custom fields, work item types, workflow and the intake form",
        "scope": "project",
        "actions": ("create", "edit", "delete"),
        "segments": (
            "states",
            "issue-labels",
            "bulk-create-labels",
            "estimates",
            "project-estimates",
            "custom-fields",
            "workflow",
            "work-item-types",
            "project-deploy-boards",
            "intake-form",
        ),
        "action_labels": {
            "create": "Add states, labels, estimates and custom fields",
            "edit": "Change them and the workflow",
            "delete": "Delete them",
        },
    },
    {
        "key": "project_members",
        "label": "Project members",
        "description": "Adding people to a project, changing their project role and removing them",
        "scope": "project",
        "actions": ("create", "edit", "delete"),
        "segments": ("members", "project-members", "invitations"),
        "action_labels": {
            "create": "Add people to a project",
            "edit": "Change someone’s project role",
            "delete": "Remove people from a project",
        },
    },
    {
        "key": "projects",
        "label": "Projects",
        "description": "Creating projects, changing their details, archiving and deleting them",
        "scope": "workspace",
        "actions": ("create", "edit", "delete"),
        "segments": (),
        "action_labels": {
            "create": "Create new projects",
            "edit": "Change project details and archive projects",
            "delete": "Delete projects",
        },
    },
    {
        "key": "workspace_members",
        "label": "Workspace members",
        "description": "Inviting people to the workspace, changing their role and removing them",
        "scope": "workspace",
        "actions": ("create", "edit", "delete"),
        "segments": ("members", "invitations", "workspace-members"),
        "action_labels": {
            "create": "Invite people to the workspace",
            "edit": "Change someone’s workspace role",
            "delete": "Remove people from the workspace",
        },
    },
    {
        "key": "all_projects",
        "label": "All Projects",
        "description": "The All Projects page in the sidebar: every project, also ones they are not in",
        "scope": "workspace",
        "actions": ("view",),
        "segments": (),
        "action_labels": {"view": "See the All Projects page with every project of the workspace"},
    },
    {
        "key": "analytics",
        "label": "Analytics",
        "description": "Workspace and project analytics",
        "scope": "workspace",
        "actions": ("view",),
        "segments": (
            "analytics",
            "advance-analytics",
            "advance-analytics-stats",
            "advance-analytics-charts",
            "analytic-view",
            "saved-analytic-view",
            "default-analytics",
            "project-stats",
        ),
        "action_labels": {"view": "See Analytics"},
    },
    {
        "key": "exports",
        "label": "Exports",
        "description": "Exporting work items and analytics",
        "scope": "workspace",
        "actions": ("create",),
        "segments": ("export-issues", "export-analytics"),
        "action_labels": {"create": "Export work items and analytics"},
    },
]
FEATURE_KEYS = {feature["key"] for feature in FEATURES}
FEATURE_ACTIONS = {feature["key"]: feature["actions"] for feature in FEATURES}

_PROJECT_SEGMENTS = {
    segment: feature["key"] for feature in FEATURES if feature["scope"] == "project" for segment in feature["segments"]
}
# analytics and exports live under a project too (advance-analytics, exports of its work items)
_PROJECT_SEGMENTS.update(
    {
        segment: feature["key"]
        for feature in FEATURES
        if feature["key"] in ("analytics", "exports")
        for segment in feature["segments"]
    }
)
_WORKSPACE_SEGMENTS = {
    segment: feature["key"]
    for feature in FEATURES
    if feature["scope"] == "workspace"
    for segment in feature["segments"]
}

_FULL = dict.fromkeys(ACTIONS, True)
_NONE = dict.fromkeys(ACTIONS, False)
_VIEW_ONLY = {**_NONE, "view": True}


def _defaults():
    """The built-in rules of each role, as shown in the settings before an admin changes anything."""
    member = {
        "work_items": _FULL,
        "comments": _FULL,
        "sprints": _FULL,
        "modules": _FULL,
        "views": _FULL,
        "pages": _FULL,
        "intake": _FULL,
        # payments, the SOW and who fills each role (adding a resource adds the person to the project) are for
        # admins: members see them, an admin can allow more in Settings → Roles & access
        "milestones": _VIEW_ONLY,
        "resources": _VIEW_ONLY,
        "deliverables": _VIEW_ONLY,
        "project_settings": _NONE,
        "project_members": _NONE,
        "projects": _NONE,
        "workspace_members": _NONE,
        "analytics": _VIEW_ONLY,
        "exports": {**_NONE, "create": True},
        # only workspace admins see every project, until allowed here
        "all_projects": _NONE,
    }
    sub_admin = {**member, "projects": {**_NONE, "create": True}, "workspace_members": {**_NONE, "create": True}}
    client = {
        **{key: _NONE for key in FEATURE_KEYS},
        **{key: _VIEW_ONLY for key in ("work_items", "comments", "sprints", "modules", "views", "pages")},
    }
    return {
        role: {key: {action: rules[key][action] for action in FEATURE_ACTIONS[key]} for key in FEATURE_KEYS}
        for role, rules in (("sub_admin", sub_admin), ("member", member), ("client", client))
    }


DEFAULTS = _defaults()

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_PATH = re.compile(r"^/api/workspaces/(?P<slug>[^/]+)/(?P<rest>.*)$")


def _action(method, segments):
    if method in ("GET", "HEAD", "OPTIONS"):
        return "view"
    if method == "DELETE" or "bulk-delete-issues" in segments:
        return "delete"
    if method in ("PATCH", "PUT") or any("archive" in segment for segment in segments):
        return "edit"
    return "create"


_SELF_SEGMENTS = {"me", "leave", "join"}


def resolve(request):
    """(workspace slug, project id or None, feature, action) of an app API request, or None when no feature has it."""
    match = _PATH.match(request.path)
    if not match:
        return None
    slug = match.group("slug")
    segments = [segment for segment in match.group("rest").split("/") if segment]
    # what people do about themselves: leaving, their own membership, joining by invitation
    if _SELF_SEGMENTS.intersection(segments):
        return None
    method = request.method.upper()
    if len(segments) >= 2 and segments[0] == "projects" and _UUID.match(segments[1]):
        project_id, inner = segments[1], segments[2:]
        feature = next((_PROJECT_SEGMENTS[s] for s in reversed(inner) if s in _PROJECT_SEGMENTS), None)
        if feature is None and (not inner or inner == ["archive"]):
            # the project itself: its details, archiving and deleting it
            feature = "projects" if method not in ("GET", "HEAD", "OPTIONS") else None
        return (slug, project_id, feature, _action(method, inner)) if feature else None
    if segments == ["projects"] and method == "POST":
        return slug, None, "projects", "create"
    feature = next((_WORKSPACE_SEGMENTS[s] for s in reversed(segments) if s in _WORKSPACE_SEGMENTS), None)
    return (slug, None, feature, _action(method, segments)) if feature else None


def role_key(workspace_role, is_sub_admin=False, project_role=None):
    """The role whose rules apply: the workspace role, lowered in a project where they have a lower project role (a
    project admin keeps their workspace role's rules)."""
    role = workspace_role if project_role is None else min(workspace_role, project_role)
    if role == ADMIN:
        return "admin"
    if role == MEMBER:
        return "sub_admin" if is_sub_admin else "member"
    return "client"


def policy_rules(workspace_id):
    policy = WorkspaceAccessPolicy.objects.filter(workspace_id=workspace_id).first()
    return policy.rules if policy else {}


def explicit_access(rules, custom, role, feature, action):
    """True (allowed) or False (denied) where an admin set it — the person's custom access first — else None."""
    custom_value = (custom or {}).get(feature, {}).get(action)
    if isinstance(custom_value, bool):
        return custom_value
    role_value = (rules or {}).get(role, {}).get(feature, {}).get(action)
    return role_value if isinstance(role_value, bool) else None


def decide(request):
    """None (the built-in rules decide), True (allowed by the settings) or False (denied), cached on the request."""
    if hasattr(request, "_access_decision"):
        return request._access_decision
    decision = None
    resolved = resolve(request) if request.user.is_authenticated else None
    if resolved:
        slug, project_id, feature, action = resolved
        if action in FEATURE_ACTIONS.get(feature, ()):
            decision = _decide(request.user, slug, project_id, feature, action)
    request._access_decision = decision
    return decision


def _decide(user, slug, project_id, feature, action):
    membership = WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True).first()
    if not membership or membership.role == ADMIN:
        return None
    project_role = None
    if project_id:
        project_member = (
            ProjectMember.objects.filter(project_id=project_id, member=user, is_active=True)
            .values("role", "project__created_by_id")
            .first()
        )
        # not in the project: the built-in rules refuse it
        if project_member is None:
            return None
        # a Sub Admin has full access to the projects they created
        if membership.is_sub_admin and project_member["project__created_by_id"] == user.id:
            return None
        project_role = project_member["role"]
    role = role_key(membership.role, membership.is_sub_admin, project_role)
    value = explicit_access(policy_rules(membership.workspace_id), membership.custom_access, role, feature, action)
    if value is None and role in ("sub_admin", "member") and not DEFAULTS[role][feature][action]:
        # what the built-in rules deny is denied in every project, whatever their project role; what they allow is
        # left to the endpoint's own checks (e.g. only the author edits a comment)
        return False
    return value


def workspace_access(user, slug, feature, action):
    """What an admin set for the person's workspace role (or for them) — True, False or None (built-in rule)."""
    membership = WorkspaceMember.objects.filter(workspace__slug=slug, member=user, is_active=True).first()
    if not membership or membership.role == ADMIN:
        return None
    role = role_key(membership.role, membership.is_sub_admin)
    return explicit_access(policy_rules(membership.workspace_id), membership.custom_access, role, feature, action)


def is_granted(request):
    """The settings allow this request although the role checks of the endpoint would refuse it."""
    return decide(request) is True


def is_denied(request):
    return decide(request) is False


def effective_access(membership, project_role=None):
    """Every feature and action for a member: {feature: {action: {"allowed": bool, "set": bool}}} — `set` when an
    admin chose it (role rule or custom access) rather than the built-in rule."""
    if membership.role == ADMIN:
        return {key: {a: {"allowed": True, "set": False} for a in FEATURE_ACTIONS[key]} for key in FEATURE_KEYS}
    role = role_key(membership.role, membership.is_sub_admin, project_role)
    rules = policy_rules(membership.workspace_id)
    result = {}
    for key in FEATURE_KEYS:
        result[key] = {}
        for action in FEATURE_ACTIONS[key]:
            value = explicit_access(rules, membership.custom_access, role, key, action)
            result[key][action] = {
                "allowed": DEFAULTS[role][key][action] if value is None else value,
                "set": value is not None,
            }
    return result
