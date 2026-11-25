# HLIS Flow — External API (v1)

Read-only API for other apps (mobile, dashboards, integrations). Log in with a user's email and password, then:

1. list the user's projects (the same list as **My Projects**),
2. list every work item of a project (all statuses),
3. get one work item with all its details.

It is separate from the app's own API: its own URLs (`/api/ext/v1/`), its own login tokens. Using it changes
nothing in the app.

---

## Base URL

| Environment | Base URL                                                                                               |
| ----------- | ------------------------------------------------------------------------------------------------------ |
| Production  | `https://16-112-0-28.sslip.io/api/ext/v1` — live after the next deploy (it adds the API and its table) |
| Local       | `http://localhost:8000/api/ext/v1`                                                                     |

All paths below are relative to the base URL and **end with a slash** (`/projects/`, not `/projects`).

## Headers

| Header          | When                       | Value                                                  |
| --------------- | -------------------------- | ------------------------------------------------------ |
| `Content-Type`  | Login (body is JSON)       | `application/json`                                     |
| `Authorization` | Every request except login | `Bearer <token>` — the `token` from the login response |
| `Accept`        | Optional                   | `application/json`                                     |

Nothing else is needed: no cookies, no CSRF token, no workspace header.

## Flow

```
POST /auth/login/                  → token
GET  /projects/                    → pick a project id
GET  /projects/{project_id}/work-items/   → pick a work item id
GET  /work-items/{work_item_id}/   → full details
POST /auth/logout/                 → token stops working (optional)
```

- A token is valid for **30 days** (`expires_at` in the login response). After that, after logout, or when the user's
  password is changed or reset, requests answer `401` — log in again.
- Each login creates a new token; tokens from other logins keep working until they expire or are logged out.
- Only the projects the user is a member of are visible. Asking for another project or work item answers `404`.

---

## 1. Log in

`POST /auth/login/`

**Body**

```json
{ "email": "rajendrac@hyperlinkinfosystem.com", "password": "••••••••" }
```

**Example**

```bash
curl -X POST https://16-112-0-28.sslip.io/api/ext/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"rajendrac@hyperlinkinfosystem.com","password":"YOUR_PASSWORD"}'
```

```js
const res = await fetch(`${BASE_URL}/auth/login/`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password }),
});
const { token } = await res.json();
// then on every call:  headers: { Authorization: `Bearer ${token}` }
```

**200 OK**

```json
{
  "token": "hlx_jBMPYjn6…",
  "token_type": "Bearer",
  "expires_at": "2026-12-24T12:47:44.266536+00:00",
  "user": {
    "id": "d04b6dea-b343-4f0e-b94e-afc702bd817a",
    "name": "Rajendra Chaudhari",
    "display_name": "rajendrac",
    "email": "rajendrac@hyperlinkinfosystem.com",
    "avatar_url": null
  }
}
```

| Status | `code`                    | When                                                                                                                          |
| ------ | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 400    | `MISSING_CREDENTIALS`     | email or password missing                                                                                                     |
| 400    | `INVALID_EMAIL`           | email is not a valid address                                                                                                  |
| 401    | `INVALID_CREDENTIALS`     | wrong email or password (same answer for both), or the account is disabled                                                    |
| 403    | `PASSWORD_LOGIN_DISABLED` | password sign-in is turned off on this instance (admin setting)                                                               |
| 429    | `TOO_MANY_FAILED_LOGINS`  | 10 wrong passwords for this email in 15 minutes — wait 15 minutes                                                             |
| 429    | —                         | more than 10 login attempts a minute from one IP address; body `{"error_code": 5900, "error_message": "RATE_LIMIT_EXCEEDED"}` |

Accounts that sign in only with Google/GitHub (no password) cannot use this login.

## 2. Log out (optional)

`POST /auth/logout/` — header `Authorization: Bearer <token>`. No body.

**204 No Content**. The token stops working.

## 3. Who am I (optional)

`GET /me/` → the `user` object of the token (same shape as in the login response).

---

## 4. My projects

`GET /projects/`

The projects the user is an active member of — the same list as **My Projects** in the app. Archived and deleted
projects are not included, nor projects of a workspace the user has left. Sorted by name (as the My Projects
screen).

**Query parameters (all optional)**

| Name        | Example                | Meaning                                |
| ----------- | ---------------------- | -------------------------------------- |
| `search`    | `zydus`                | name or key contains this text         |
| `workspace` | `hyperlink-infosystem` | only projects of this workspace (slug) |

**Example**

```bash
curl https://16-112-0-28.sslip.io/api/ext/v1/projects/ \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK**

```json
{
  "count": 2,
  "results": [
    {
      "id": "c5c564ed-3a87-4837-84e4-1ff5f2cc2e63",
      "name": "Zydus DMS Support",
      "identifier": "ZYDUSDMSSU",
      "workspace": { "id": "…", "slug": "hyperlink-infosystem", "name": "Hyperlink Infosystem" },
      "description": "",
      "project_type": "fixed_cost",
      "network": "public",
      "lead": { "id": "…", "name": "Parth Patel", "display_name": "parth.patelba", "email": "…", "avatar_url": null },
      "your_role": "admin",
      "logo_props": { "emoji": { "value": "128578" }, "in_use": "emoji" },
      "created_at": "2026-10-30T09:12:01.120000+00:00",
      "updated_at": "2026-11-24T05:40:10.000000+00:00"
    }
  ]
}
```

| Field                      | Type              | Notes                                                                                                                |
| -------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------- |
| `id`                       | uuid              | use it in `/projects/{id}/work-items/`                                                                               |
| `name`                     | string            | project name                                                                                                         |
| `identifier`               | string            | project key, e.g. `ZYDUSDMSSU` (work item keys are `ZYDUSDMSSU-9`)                                                   |
| `workspace`                | object            | `id`, `slug`, `name`                                                                                                 |
| `description`              | string            | may be empty                                                                                                         |
| `project_type`             | string            | e.g. `fixed_cost`                                                                                                    |
| `network`                  | string            | `public` or `private`                                                                                                |
| `lead`                     | user \| null      | project lead                                                                                                         |
| `your_role`                | string            | the user's role in the project: `admin`, `member` or `guest` (a guest may see only their own work items — see below) |
| `logo_props`               | object            | the project's icon/emoji as the app stores it                                                                        |
| `created_at`, `updated_at` | ISO 8601 datetime |                                                                                                                      |

---

## 5. Work items of a project

`GET /projects/{project_id}/work-items/`

Every work item of the project, **in every status** (To Do, In Progress, In QA, Reopen, Done, …), newest first —
the same items as the project's Work items screen (drafts, archived work items and requests still waiting in Intake
are not included). Returned a page at a time.

> **Guests:** a user whose `your_role` is `guest`, in a project that does not let guests see every work item, gets
> only the work items they created — the same as in the app. Other work items answer `404` in the details.

**Query parameters (all optional)**

| Name          | Default | Example             | Meaning                                                                                                 |
| ------------- | ------- | ------------------- | ------------------------------------------------------------------------------------------------------- |
| `page`        | `1`     | `2`                 | page number (starts at 1)                                                                               |
| `per_page`    | `100`   | `50`                | items per page, 1–500                                                                                   |
| `search`      | —       | `invoice`           | title contains this text, or the number matches (`9` finds `ZYDUSDMSSU-9`)                              |
| `state_group` | —       | `started,unstarted` | only these status groups (comma separated): `backlog`, `unstarted`, `started`, `completed`, `cancelled` |
| `state_id`    | —       | `uuid,uuid`         | only these statuses (ids from `state.id`)                                                               |
| `priority`    | —       | `urgent,high`       | only these priorities: `urgent`, `high`, `medium`, `low`, `none`                                        |

To get everything, keep calling with `page = next_page` until `next_page` is `null`.

**Example**

```bash
curl "https://16-112-0-28.sslip.io/api/ext/v1/projects/c5c564ed-3a87-4837-84e4-1ff5f2cc2e63/work-items/?per_page=100&page=1" \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK**

```json
{
  "project": { "id": "c5c564ed-3a87-4837-84e4-1ff5f2cc2e63", "name": "Zydus DMS Support" },
  "count": 6,
  "page": 1,
  "per_page": 100,
  "total_pages": 1,
  "next_page": null,
  "results": [
    {
      "id": "8b0a…",
      "key": "ZYDUSDMSSU-9",
      "sequence_id": 9,
      "name": "E-mail notification for transactions- Shine Medicals",
      "type": { "id": "…", "name": "Bug", "color": "#EF4444" },
      "state": { "id": "…", "name": "In Progress", "group": "started", "color": "#2563EB" },
      "priority": "high",
      "priority_label": "High",
      "assignees": [
        {
          "id": "…",
          "name": "Rajendra Chaudhari",
          "display_name": "rajendrac",
          "email": "rajendrac@…",
          "avatar_url": null
        }
      ],
      "labels": [{ "id": "…", "name": "Salesforce Developer", "color": "#F59E0B" }],
      "modules": [],
      "sprint": null,
      "start_date": null,
      "due_date": null,
      "estimate": null,
      "parent": null,
      "milestone": null,
      "created_by": {
        "id": "…",
        "name": "Manish Singh",
        "display_name": "manish.singh3",
        "email": "…",
        "avatar_url": null
      },
      "updated_by": {
        "id": "…",
        "name": "Rajendra Chaudhari",
        "display_name": "rajendrac",
        "email": "…",
        "avatar_url": null
      },
      "completed_at": null,
      "created_at": "2026-11-24T04:17:12.120000+00:00",
      "updated_at": "2026-11-24T12:01:40.000000+00:00"
    }
  ]
}
```

**Work item fields (list and details)**

| Field                      | Type                 | Notes                                                            |
| -------------------------- | -------------------- | ---------------------------------------------------------------- |
| `id`                       | uuid                 | use it in `/work-items/{id}/`                                    |
| `key`                      | string               | e.g. `ZYDUSDMSSU-9`                                              |
| `sequence_id`              | number               | the number in the key                                            |
| `name`                     | string               | title                                                            |
| `type`                     | object \| null       | `id`, `name` (Feature, Task, Bug…), `color`                      |
| `state`                    | object               | the status: `id`, `name`, `group`, `color` — see _Status groups_ |
| `priority`                 | string               | `urgent`, `high`, `medium`, `low` or `none`                      |
| `priority_label`           | string               | `Urgent`, `High`, `Medium`, `Low`, `None`                        |
| `assignees`                | user[]               |                                                                  |
| `labels`                   | object[]             | `id`, `name`, `color`                                            |
| `modules`                  | object[]             | `id`, `name`                                                     |
| `sprint`                   | object \| null       | `id`, `name`, `start_date`, `end_date`                           |
| `start_date`, `due_date`   | `YYYY-MM-DD` \| null |                                                                  |
| `estimate`                 | string \| null       | estimate value, when the project uses estimates                  |
| `parent`                   | object \| null       | the parent work item (Feature): `id`, `key`, `name`              |
| `milestone`                | object \| null       | `id`, `code`, `name`                                             |
| `created_by`, `updated_by` | user \| null         | who created / last changed it                                    |
| `completed_at`             | datetime \| null     | when it reached a completed status                               |
| `created_at`, `updated_at` | datetime             |                                                                  |

**Errors**: `404 PROJECT_NOT_FOUND` (not a project of this user), `400 INVALID_PAGINATION`.

---

## 6. Work item details

`GET /work-items/{work_item_id}/`

Everything the work item's screen shows: all the fields of the list above, plus the description, watchers, queue,
custom fields, sub-work items, relations, links, attachments, reactions, comments and the history.

**Example**

```bash
curl https://16-112-0-28.sslip.io/api/ext/v1/work-items/8b0a…/ \
  -H "Authorization: Bearer $TOKEN"
```

**200 OK** (the list fields are shortened here)

```json
{
  "id": "8b0a…",
  "key": "ZYDUSDMSSU-9",
  "name": "E-mail notification for transactions- Shine Medicals",
  "type": { "id": "…", "name": "Bug", "color": "#EF4444" },
  "state": { "id": "…", "name": "In Progress", "group": "started", "color": "#2563EB" },
  "priority": "high",
  "priority_label": "High",
  "assignees": [
    { "id": "…", "name": "Rajendra Chaudhari", "display_name": "rajendrac", "email": "…", "avatar_url": null }
  ],
  "labels": [{ "id": "…", "name": "Salesforce Developer", "color": "#F59E0B" }],
  "...": "every other field of the list",

  "project": {
    "id": "c5c5…",
    "name": "Zydus DMS Support",
    "identifier": "ZYDUSDMSSU",
    "workspace": { "id": "…", "slug": "hyperlink-infosystem", "name": "Hyperlink Infosystem" }
  },
  "description_html": "<p>Whenever shine is doing any transaction in DMS, they are not getting any emails…</p>",
  "description_text": "Whenever shine is doing any transaction in DMS, they are not getting any emails…",
  "archived_at": null,
  "watchers": [
    { "id": "…", "name": "Rajendra Chaudhari", "display_name": "rajendrac", "email": "…", "avatar_url": null }
  ],
  "queues": [],
  "custom_fields": [{ "id": "…", "name": "Client ticket", "field_type": "text", "value": "SR-1042" }],
  "sub_work_items": [
    {
      "id": "…",
      "key": "ZYDUSDMSSU-10",
      "name": "Fix SMTP settings",
      "priority": "medium",
      "state": { "id": "…", "name": "To Do", "group": "unstarted", "color": "#60646C" },
      "assignees": []
    }
  ],
  "relations": [
    {
      "id": "…",
      "relation_type": "blocked_by",
      "direction": "outgoing",
      "work_item": {
        "id": "…",
        "key": "ZYDUSDMSSU-7",
        "name": "ARS PO NOT WARKING",
        "state": { "id": "…", "name": "Done", "group": "completed", "color": "#16A34A" }
      }
    }
  ],
  "links": [{ "id": "…", "title": "Spec", "url": "https://…", "created_by": { "…": "…" }, "created_at": "…" }],
  "attachments": [
    {
      "id": "…",
      "name": "mail body.png",
      "type": "image/png",
      "size": 55000,
      "url": "https://…signed-download-link…",
      "uploaded_by": { "…": "…" },
      "created_at": "…"
    }
  ],
  "reactions": [{ "reaction": "128077", "actor": { "…": "…" }, "created_at": "…" }],
  "comments": [
    {
      "id": "…",
      "author": { "…": "…" },
      "comment_html": "<p>Looking into it</p>",
      "comment_text": "Looking into it",
      "parent_id": null,
      "reactions": [],
      "edited_at": null,
      "created_at": "…",
      "updated_at": "…"
    }
  ],
  "activity": [
    {
      "id": "…",
      "actor": { "…": "…" },
      "verb": "updated",
      "field": "state",
      "old_value": "To Do",
      "new_value": "In Progress",
      "comment": "changed the state to",
      "created_at": "…"
    }
  ],
  "intake": {
    "status": "accepted",
    "source_email": "manish.singh3@zydusmedtech.com",
    "requested_by": { "…": "…" },
    "created_at": "…"
  }
}
```

**Extra fields of the details**

| Field              | Type           | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------ | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `project`          | object         | `id`, `name`, `identifier`, `workspace`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `description_html` | string         | the description as HTML (as written in the app)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `description_text` | string         | the same as plain text                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `archived_at`      | date \| null   |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `watchers`         | user[]         | people following the work item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `queues`           | object[]       | `id`, `name`, `color`, `note` — the queues it is in                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `custom_fields`    | object[]       | `id`, `name`, `field_type` (`text`, `textarea`, `number`, `date`, `select`, `multi_select`, `checkbox`, `url`, `user`), `value` — as stored (text, number, date `YYYY-MM-DD`, option or list of options, `true`/`false`); for `user` (People) a list of user objects                                                                                                                                                                                                                                                                      |
| `sub_work_items`   | object[]       | `id`, `key`, `name`, `state`, `priority`, `assignees`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `relations`        | object[]       | `relation_type` (see below), `direction` (`outgoing`: this item _relation_type_ the other; `incoming`: the other way round), `work_item` (`id`, `key`, `name`, `state`)                                                                                                                                                                                                                                                                                                                                                                   |
| `links`            | object[]       | `id`, `title`, `url`, `created_by`, `created_at`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `attachments`      | object[]       | `id`, `name`, `type` (MIME), `size` (bytes), `url`, `uploaded_by`, `created_at` — `url` is a signed download link valid for **1 hour**; call the details again for a fresh one                                                                                                                                                                                                                                                                                                                                                            |
| `reactions`        | object[]       | `reaction` (emoji code), `actor`, `created_at`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `comments`         | object[]       | oldest first: `id`, `author`, `comment_html`, `comment_text`, `parent_id` (a reply), `reactions` (`reaction`, `actor`, `created_at`), `edited_at`, `created_at`, `updated_at`                                                                                                                                                                                                                                                                                                                                                             |
| `activity`         | object[]       | the history, oldest first (comments are under `comments`): `id`, `actor`, `verb` (`created`, `updated`, `deleted`, `removed`), `field` (what changed: `state`, `priority`, `assignees`, `labels`, `name`, `description`, `start_date`, `target_date`, `attachment`, `link`, `parent`, `cycles`, `modules`, `intake`, … — `null` for "created the work item"), `old_value`, `new_value`, `comment` (the app's wording), `created_at`. `actor` can be `null`, and for history imported from Jira it has only a `name` (other fields `null`) |
| `intake`           | object \| null | when the work item came in through Intake: `status` (`pending`, `accepted`, `declined`, `duplicate`, `snoozed`), `source_email`, `requested_by`, `created_at`                                                                                                                                                                                                                                                                                                                                                                             |

**Errors**: `404 WORK_ITEM_NOT_FOUND` (unknown id, or not in a project of this user).

---

## Reference

### User object

`{ "id": uuid, "name": string, "display_name": string, "email": string, "avatar_url": string | null }`

`name` is the full name when set, else the display name.

### Status groups (`state.group`)

| Group       | Meaning     | Default statuses           |
| ----------- | ----------- | -------------------------- |
| `backlog`   | not planned | —                          |
| `unstarted` | to do       | To Do                      |
| `started`   | in progress | In Progress, In QA, Reopen |
| `completed` | done        | Done                       |
| `cancelled` | dropped     | —                          |

Projects can rename statuses or add their own, so use `state.group` (not the name) to decide whether a work item is
done.

### Relation types (`relations[].relation_type`)

`relates_to`, `duplicate`, `blocked_by`, `start_before`, `finish_before`, `implemented_by`.

### Errors

| Status | Body                                                                  | When                                                                                          |
| ------ | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 400    | `{"error": "…", "code": "…"}`                                         | wrong parameters — see the `code` of each endpoint                                            |
| 400    | `{"detail": "JSON parse error - …"}`                                  | the login body is not valid JSON                                                              |
| 401    | `{"detail": "…"}`                                                     | no token, wrong token, expired, logged out or password changed — log in again                 |
| 403    | `{"error": "…", "code": "PASSWORD_LOGIN_DISABLED"}`                   | login only                                                                                    |
| 404    | `{"error": "…", "code": "PROJECT_NOT_FOUND"}` / `WORK_ITEM_NOT_FOUND` | not found, or not visible to this user                                                        |
| 404    | (not JSON)                                                            | the path does not exist — check the URL and its trailing slash                                |
| 405    | `{"detail": "Method \"…\" not allowed."}`                             | wrong method (e.g. GET on the login)                                                          |
| 429    | `{"error_code": 5900, "error_message": "RATE_LIMIT_EXCEEDED"}`        | too many requests: 10 logins a minute per IP, 300 requests a minute per user — wait and retry |
| 429    | `{"error": "…", "code": "TOO_MANY_FAILED_LOGINS"}`                    | 10 wrong passwords for one email in 15 minutes                                                |

Check the HTTP status first; then read `code` (or `detail` / `error_message`) for the reason.

### Calling from a browser on another domain

Mobile apps and servers can call the API directly. A web page served from another domain is blocked by the
browser unless that domain is added to `CORS_ALLOWED_ORIGINS` on the server — ask the backend team to add it.

### Postman

Import `HLIS-Flow-External-API.postman_collection.json` (same folder). Set the `base_url` (local by default; use the
production URL above once it is deployed), `email` and `password` variables, then run **Log in** — it saves the token,
and **My projects** / **Project work items** save the first `project_id` / `work_item_id` for the next requests.
