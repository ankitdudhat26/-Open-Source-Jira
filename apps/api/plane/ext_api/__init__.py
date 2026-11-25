# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""External read-only API (/api/ext/v1/): log in with email and password, then list your projects (as in My
Projects), a project's work items and a work item's full details. Documented in apps/api/docs/external-api/README.md.

It is separate from the app's own API (/api/) and the public API (/api/v1/): its own URLs, sessions and
authentication, so nothing that exists changes."""
