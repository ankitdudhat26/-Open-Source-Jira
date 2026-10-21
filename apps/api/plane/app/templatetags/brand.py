# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Branding for server rendered templates (emails): {% load brand %} then {% brand_name %} / {% brand_logo_url %}."""

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def brand_name():
    return settings.BRAND_NAME


@register.simple_tag
def brand_logo_url():
    """The logo served by the web app itself, so emails do not load images from any third party."""
    base_url = (settings.APP_BASE_URL or settings.WEB_URL or "").rstrip("/")
    return f"{base_url}/icons/icon-192x192.png"
