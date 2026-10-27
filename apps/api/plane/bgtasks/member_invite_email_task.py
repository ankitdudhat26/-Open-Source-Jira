# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from email.mime.image import MIMEImage
from pathlib import Path

# Django imports
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

# Module imports
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.email import generate_plain_text_from_html

# the app icon travels inside the email: mail apps cannot load images from a local or private app address
LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "logos" / "app-icon.png"
LOGO_CID = "app-logo"


def send_member_invite_email(user, workspace, inviter, invite_url, sign_in_url, valid_days):
    """Email a workspace member the link to set a password and sign in.

    Sent while the admin waits (not in the background), so a wrong mail server setup is reported to them
    instead of the invite silently never arriving.
    """
    (
        EMAIL_HOST,
        EMAIL_HOST_USER,
        EMAIL_HOST_PASSWORD,
        EMAIL_PORT,
        EMAIL_USE_TLS,
        EMAIL_USE_SSL,
        EMAIL_FROM,
    ) = get_email_configuration()
    context = {
        "first_name": user.first_name or user.display_name or "there",
        "email": user.email,
        "workspace_name": workspace.name,
        "inviter": inviter.display_name or inviter.first_name or "Your workspace admin",
        "invite_url": invite_url,
        "sign_in_url": sign_in_url,
        "valid_days": valid_days,
        "logo_src": f"cid:{LOGO_CID}",
    }
    html_content = render_to_string("emails/invitations/member_access.html", context)
    connection = get_connection(
        host=EMAIL_HOST,
        port=int(EMAIL_PORT),
        username=EMAIL_HOST_USER,
        password=EMAIL_HOST_PASSWORD,
        use_tls=EMAIL_USE_TLS == "1",
        use_ssl=EMAIL_USE_SSL == "1",
        timeout=30,
    )
    message = EmailMultiAlternatives(
        subject=f"{context['inviter']} invited you to {workspace.name} on {settings.BRAND_NAME}",
        body=generate_plain_text_from_html(html_content),
        from_email=EMAIL_FROM,
        to=[user.email],
        connection=connection,
    )
    message.attach_alternative(html_content, "text/html")
    # inline image (shown in the header, not as an attachment)
    message.mixed_subtype = "related"
    logo = MIMEImage(LOGO_PATH.read_bytes(), "png")
    logo.add_header("Content-ID", f"<{LOGO_CID}>")
    logo.add_header("Content-Disposition", "inline", filename="logo.png")
    message.attach(logo)
    message.send()
