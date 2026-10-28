# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.utils.attachment_preview import inline_preview_content_type


@pytest.mark.unit
class TestInlinePreviewContentType:
    @pytest.mark.parametrize(
        "file_name, stored_type, expected",
        [
            ("report.pdf", "application/pdf", "application/pdf"),
            ("clip.mp4", "video/mp4", "video/mp4"),
            ("photo.png", "image/png", "image/png"),
            # A missing or generic stored type falls back to the file name
            ("report.pdf", None, "application/pdf"),
            ("report.pdf", "application/octet-stream", "application/pdf"),
            ("photo.JPG", "", "image/jpeg"),
            # The file name wins over a misleading stored type
            ("report.pdf", "application/x-unknown", "application/pdf"),
            # Unknown extensions fall back to the stored type
            ("clip.unknownext", "video/mp4", "video/mp4"),
        ],
    )
    def test_previewable_files(self, file_name, stored_type, expected):
        assert inline_preview_content_type(file_name, stored_type) == expected

    @pytest.mark.parametrize(
        "file_name, stored_type",
        [
            ("notes.txt", "text/plain"),
            ("data.csv", "text/csv"),
            ("data.csv", "application/vnd.ms-excel"),
            ("readme.md", None),
        ],
    )
    def test_text_is_served_as_plain_text(self, file_name, stored_type):
        assert inline_preview_content_type(file_name, stored_type) == "text/plain; charset=utf-8"

    @pytest.mark.parametrize(
        "file_name, stored_type",
        [
            ("page.html", "text/html"),
            ("logo.svg", "image/svg+xml"),
            ("feed.xml", None),
            ("app.js", "text/javascript"),
            # The name or the stored type alone is enough to refuse
            ("page.html", "text/plain"),
            ("notes.txt", "text/html; charset=utf-8"),
        ],
    )
    def test_script_capable_files_stay_downloads(self, file_name, stored_type):
        assert inline_preview_content_type(file_name, stored_type) is None

    def test_unknown_type_stays_a_download(self):
        assert inline_preview_content_type("archive.unknownext", None) is None
