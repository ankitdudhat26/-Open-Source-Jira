# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import mimetypes

# Django imports
from django.conf import settings


def inline_preview_content_type(file_name, stored_type=None):
    """Content type to serve an attachment inline with (for the in-app viewer),
    or None when it must stay a download.

    Script-capable types (HTML, SVG, XML, JS), judged by the stored type or the file
    name, are never served inline. Text is served as plain text so the browser shows
    it instead of downloading (text/csv) or rendering it.
    """
    stored = (stored_type or "").split(";")[0].strip().lower()
    guessed = (mimetypes.guess_type(file_name or "")[0] or "").lower()
    if stored in settings.SCRIPT_CAPABLE_MIME_TYPES or guessed in settings.SCRIPT_CAPABLE_MIME_TYPES:
        return None

    # The name decides when it's known: browsers often upload e.g. .csv as application/vnd.ms-excel
    content_type = guessed or (stored if stored != "application/octet-stream" else "")
    if not content_type:
        return None
    if content_type.startswith("text/"):
        return "text/plain; charset=utf-8"
    return content_type
