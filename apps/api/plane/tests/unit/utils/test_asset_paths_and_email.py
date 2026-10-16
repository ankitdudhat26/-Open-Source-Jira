# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re
import uuid

import pytest

from plane.license.utils import instance_value
from plane.utils.asset_paths import asset_storage_key


@pytest.mark.unit
class TestAssetStorageKey:
    def test_workspace_files_are_grouped_by_kind(self, settings):
        settings.AWS_S3_FOLDER = "plane"
        workspace_id = uuid.uuid4()

        key = asset_storage_key("spec.pdf", entity_type="ISSUE_ATTACHMENT", workspace_id=workspace_id)

        assert re.fullmatch(rf"plane/workspaces/{workspace_id}/attachments/[0-9a-f]{{32}}-spec\.pdf", key)

    def test_user_files_go_under_the_user(self, settings):
        settings.AWS_S3_FOLDER = "plane"
        user_id = uuid.uuid4()

        key = asset_storage_key("me.png", entity_type="USER_AVATAR", user_id=user_id)

        assert key.startswith(f"plane/users/{user_id}/avatars/")

    def test_unknown_kind_and_custom_root_folder(self, settings):
        settings.AWS_S3_FOLDER = "/apps/plane/"

        key = asset_storage_key("a.txt", entity_type="SOMETHING_NEW", workspace_id="w1")

        assert key.startswith("apps/plane/workspaces/w1/files/")

    def test_without_root_folder(self, settings):
        settings.AWS_S3_FOLDER = ""

        assert asset_storage_key("a.txt", entity_type="WORKSPACE_LOGO", workspace_id="w1").startswith(
            "workspaces/w1/logos/"
        )


@pytest.mark.unit
class TestSendGridEmailConfiguration:
    def test_sendgrid_key_switches_smtp_to_sendgrid(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "SG.test-key")
        monkeypatch.setenv("MAIL_FROM_EMAIL", "noreply@example.com")
        monkeypatch.setenv("MAIL_FROM_NAME", "Hyperlink InfoSystem")

        assert instance_value.get_email_configuration() == (
            "smtp.sendgrid.net",
            "apikey",
            "SG.test-key",
            "587",
            "1",
            "0",
            "Hyperlink InfoSystem <noreply@example.com>",
        )
        assert instance_value.is_sendgrid_configured()

    def test_without_sendgrid_key_the_instance_settings_are_used(self, monkeypatch):
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        sentinel = ("smtp.example.com", "user", "pass", "25", "0", "0", "Team <t@example.com>")
        monkeypatch.setattr(instance_value, "get_configuration_value", lambda keys: sentinel)

        assert instance_value.get_email_configuration() == sentinel
        assert not instance_value.is_sendgrid_configured()
