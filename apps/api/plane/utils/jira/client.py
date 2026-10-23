# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A strictly read only Jira Cloud client.

Only HTTP GET requests are ever sent: there is no method in this class that can create, change or delete
anything in Jira. Rate limits (429) and short outages (5xx) are retried with back off.
"""

import csv
import io
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import requests

API = "/rest/api/3"
AGILE = "/rest/agile/1.0"


class JiraError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def normalize_site_url(site_url):
    """'acme.atlassian.net' / 'https://acme.atlassian.net/jira/...' -> 'https://acme.atlassian.net'."""
    value = (site_url or "").strip()
    if not value:
        raise JiraError("Jira site URL is required.")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise JiraError("Use the https address of your Jira site, e.g. https://your-team.atlassian.net")
    return f"https://{parsed.netloc}"


class JiraClient:
    MAX_RETRIES = 5
    TIMEOUT = 30

    def __init__(self, site_url, email, api_token, session=None):
        self.base_url = normalize_site_url(site_url)
        self.session = session or requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    # the only way this client talks to Jira
    def _get(self, path, params=None, raw=False):
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        if not url.startswith(self.base_url):
            raise JiraError("Refusing to call a URL outside the Jira site.")
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.get(url, params=params, timeout=self.TIMEOUT, allow_redirects=True)
            except requests.RequestException as error:
                if attempt == self.MAX_RETRIES - 1:
                    raise JiraError(f"Could not reach Jira: {error}") from error
                time.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.MAX_RETRIES - 1:
                    raise JiraError(f"Jira is busy (HTTP {response.status_code}). Try again later.", 429)
                retry_after = response.headers.get("Retry-After")
                time.sleep(min(float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt, 60))
                continue
            if response.status_code == 401:
                raise JiraError("Jira rejected the email / API token.", 401)
            if response.status_code == 403:
                raise JiraError("This Jira account has no permission to read that.", 403)
            if response.status_code == 404:
                raise JiraError("Not found in Jira.", 404)
            if response.status_code >= 400:
                raise JiraError(f"Jira returned HTTP {response.status_code}.", response.status_code)
            return response.content if raw else response.json()
        raise JiraError("Jira did not answer.")

    # ---- account / projects ---------------------------------------------------------------------------------
    def myself(self):
        return self._get(f"{API}/myself")

    def projects(self):
        start, items = 0, []
        while True:
            page = self._get(
                f"{API}/project/search",
                {"startAt": start, "maxResults": 50, "expand": "description,lead,insight"},
            )
            values = page.get("values", [])
            items.extend(values)
            if page.get("isLast", True) or not values:
                return items
            start += len(values)

    def fields(self):
        """Every field of the Jira site: [{id, name, custom, schema: {type, items, custom}}]."""
        return self._get(f"{API}/field")

    def project(self, key):
        return self._get(f"{API}/project/{key}", {"expand": "description,lead"})

    def can_browse(self, project_key):
        """Whether this account may read the project's work items (Jira lists projects it cannot browse)."""
        permissions = self._get(
            f"{API}/mypermissions", {"projectKey": project_key, "permissions": "BROWSE_PROJECTS"}
        ).get("permissions", {})
        return bool((permissions.get("BROWSE_PROJECTS") or {}).get("havePermission"))

    def project_statuses(self, key):
        """Statuses used by the project's issue types: [{id, name, statusCategory: {key}}] (de-duplicated)."""
        statuses = {}
        for issue_type in self._get(f"{API}/project/{key}/statuses"):
            for status in issue_type.get("statuses", []):
                statuses.setdefault(status["id"], status)
        return list(statuses.values())

    # ---- people ---------------------------------------------------------------------------------------------
    def users(self):
        """Every user of the Jira site (people, apps and customers), page by page."""
        start, users = 0, []
        while True:
            page = self._get(f"{API}/users/search", {"startAt": start, "maxResults": 200})
            if not isinstance(page, list) or not page:
                return users
            users.extend(page)
            if len(page) < 200:
                return users
            start += len(page)

    def groups(self):
        return list(self._offset_pages(f"{API}/group/bulk", "values", {}))

    def group_members(self, group_id):
        return list(
            self._offset_pages(f"{API}/group/member", "values", {"groupId": group_id, "includeInactiveUsers": "false"})
        )

    def assignable_users(self, project_key):
        """Everyone Jira lets you assign work to in the project (its permission scheme, groups and roles)."""
        start, users = 0, []
        while True:
            page = self._get(
                f"{API}/user/assignable/search", {"project": project_key, "startAt": start, "maxResults": 100}
            )
            if not isinstance(page, list) or not page:
                return users
            users.extend(page)
            if len(page) < 100:
                return users
            start += len(page)

    def project_roles(self, project_key):
        """[{name, actors: [...]}] of a project (Administrators, Developers, ...)."""
        roles = []
        for url in (self._get(f"{API}/project/{project_key}/role") or {}).values():
            try:
                roles.append(self._get(url))
            except JiraError:
                continue
        return roles

    # ---- issues -----------------------------------------------------------------------------------------------
    def issues(self, project_key, fields="*all"):
        """Every issue of the project (oldest first), page by page."""
        token = None
        while True:
            params = {
                "jql": f'project = "{project_key}" ORDER BY created ASC',
                "fields": fields,
                "maxResults": 100,
            }
            if token:
                params["nextPageToken"] = token
            page = self._get(f"{API}/search/jql", params)
            yield from page.get("issues", [])
            token = page.get("nextPageToken")
            if not token or page.get("isLast", False):
                return

    def _offset_pages(self, path, key, params=None):
        start = 0
        while True:
            page = self._get(path, {**(params or {}), "startAt": start, "maxResults": 100})
            values = page.get(key, [])
            yield from values
            total = page.get("total")
            start += len(values)
            if not values or page.get("isLast") or (total is not None and start >= total):
                return

    def comments(self, issue_id):
        return list(self._offset_pages(f"{API}/issue/{issue_id}/comment", "comments", {"orderBy": "created"}))

    def changelog(self, issue_id):
        return list(self._offset_pages(f"{API}/issue/{issue_id}/changelog", "values"))

    def watchers(self, issue_id):
        return self._get(f"{API}/issue/{issue_id}/watchers").get("watchers", [])

    def attachment_content(self, content_url):
        return self._get(content_url, raw=True)

    @contextmanager
    def attachment_stream(self, content_url):
        """The file of an attachment as a stream (GET only), for copying big files without holding them in memory."""
        url = content_url if content_url.startswith("http") else f"{self.base_url}{content_url}"
        if not url.startswith(self.base_url):
            raise JiraError("Refusing to call a URL outside the Jira site.")
        try:
            response = self.session.get(url, timeout=(30, 300), stream=True, allow_redirects=True)
        except requests.RequestException as error:
            raise JiraError(f"Could not reach Jira: {error}") from error
        try:
            if response.status_code >= 400:
                raise JiraError(f"Jira returned HTTP {response.status_code}.", response.status_code)
            response.raw.decode_content = True
            yield response.raw
        finally:
            response.close()

    # ---- sprints (Jira Software) -----------------------------------------------------------------------------
    def boards(self, project_key):
        return list(self._offset_pages(f"{AGILE}/board", "values", {"projectKeyOrId": project_key}))

    def sprints(self, board_id):
        return list(self._offset_pages(f"{AGILE}/board/{board_id}/sprint", "values"))

    def sprint_issue_ids(self, sprint_id):
        return [
            issue["id"] for issue in self._offset_pages(f"{AGILE}/sprint/{sprint_id}/issue", "issues", {"fields": "id"})
        ]


ADMIN_API = "https://api.atlassian.com/admin"


class AtlassianAdminClient(JiraClient):
    """The organization's user directory (admin.atlassian.com → Users), read only like JiraClient: GET only."""

    def __init__(self, api_key, session=None):
        self.base_url = "https://api.atlassian.com"
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "Authorization": f"Bearer {api_key}"})

    def _cursor_pages(self, path, params=None):
        cursor = None
        for _ in range(500):
            page = self._get(path, {**(params or {}), **({"cursor": cursor} if cursor else {})})
            yield from page.get("data") or []
            following = (page.get("links") or {}).get("next")
            if not following or following == cursor:
                return
            if following.startswith("http"):
                path, params, cursor = following, None, None
            else:
                cursor = following

    def orgs(self):
        return [
            {"id": org.get("id"), "name": (org.get("attributes") or {}).get("name") or ""}
            for org in self._cursor_pages(f"{ADMIN_API}/v1/orgs")
        ]

    def users(self, org_id):
        """{accountId: {email, name, status, org_admin, time_zone, avatar}} of everyone in the organization."""
        people = {}
        try:
            directories = list(self._cursor_pages(f"{ADMIN_API}/v2/orgs/{org_id}/directories"))
            for directory in directories:
                for user in self._cursor_pages(
                    f"{ADMIN_API}/v2/orgs/{org_id}/directories/{directory['directoryId']}/users", {"limit": 100}
                ):
                    people[user.get("accountId")] = directory_person(
                        email=user.get("email"),
                        name=user.get("name") or user.get("nickname"),
                        status=user.get("accountStatus") or user.get("status"),
                        org_admin=any("org-admin" in str(role) for role in user.get("platformRoles") or []),
                        time_zone=user.get("timeZone"),
                        avatar=user.get("avatar") or user.get("picture"),
                    )
        except JiraError:
            people = {}
        if not any(person["email"] for person in people.values()):
            # older organizations: the v1 user list
            for user in self._cursor_pages(f"{ADMIN_API}/v1/orgs/{org_id}/users"):
                people[user.get("account_id")] = directory_person(
                    email=user.get("email"),
                    name=user.get("name"),
                    status=user.get("account_status"),
                    avatar=user.get("picture"),
                )
        people.pop(None, None)
        return people


def directory_person(email=None, name=None, status=None, org_admin=False, time_zone=None, avatar=None):
    return {
        "email": (email or "").strip().lower(),
        "name": (name or "").strip(),
        "active": (status or "active").strip().lower() in ("active", "enabled"),
        "org_admin": bool(org_admin),
        "time_zone": time_zone or "",
        "avatar": avatar or "",
    }


def parse_user_export(text):
    """The CSV of admin.atlassian.com → Users → Export users: {accountId: person} (columns found by name)."""
    rows = list(csv.reader(io.StringIO((text or "").lstrip("\ufeff"))))
    if len(rows) < 2:
        raise JiraError("The file has no users.")
    header = [cell.strip().lower() for cell in rows[0]]

    def column(*names, contains=None):
        for index, cell in enumerate(header):
            if cell in names or (contains and contains in cell):
                return index
        return None

    id_col = column("user id", "account id", "atlassian id", "accountid", "id")
    email_col = column("email", "email address", contains="email")
    name_col = column("user name", "name", "full name", "display name")
    status_col = column("user status", "status", "account status")
    role_col = column("org role", "organization role", "role")
    if email_col is None or (id_col is None and name_col is None):
        raise JiraError("Upload the users file exported from admin.atlassian.com (it needs the user and email).")
    people = {}
    for row in rows[1:]:

        def cell(index, row=row):
            return row[index].strip() if index is not None and index < len(row) else ""

        # without an id column people are matched by their name ("name:<name>")
        account_id = (
            cell(id_col) if id_col is not None else (f"name:{cell(name_col).lower()}" if cell(name_col) else "")
        )
        if not account_id:
            continue
        people[account_id] = directory_person(
            email=cell(email_col),
            name=cell(name_col),
            status=cell(status_col) or "active",
            org_admin="admin" in cell(role_col).lower(),
        )
    if not people:
        raise JiraError("The file has no users.")
    return people
