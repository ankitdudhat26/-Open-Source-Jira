# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Branding for server rendered templates (emails): {% load brand %} then {% brand_name %} / {% brand_logo_url %}."""

from django import template
from django.conf import settings
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def brand_name():
    return settings.BRAND_NAME


@register.simple_tag
def brand_logo_url():
    """The logo served by the web app itself, so emails do not load images from any third party."""
    base_url = (settings.APP_BASE_URL or settings.WEB_URL or "").rstrip("/")
    return f"{base_url}/icons/icon-192x192.png"


@register.simple_tag
def brand_header(text_color="#ffffff"):
    """Email header: the logo with the app name beside it (white text on the dark header, dark text on a light one)."""
    return format_html(
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0"><tr>'
        '<td style="vertical-align: middle; padding-right: 12px;">'
        '<img src="{}" width="40" height="40" alt="" border="0" '
        'style="display: block; border: 0; width: 40px; height: 40px;" /></td>'
        '<td style="vertical-align: middle; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, '
        'Helvetica, Arial, sans-serif; font-size: 20px; line-height: 24px; font-weight: 700; color: {};">{}</td>'
        "</tr></table>",
        brand_logo_url(),
        text_color,
        settings.BRAND_NAME,
    )
