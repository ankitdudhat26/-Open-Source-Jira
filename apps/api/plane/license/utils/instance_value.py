# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os

# Django imports
from django.conf import settings

# Module imports
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import decrypt_data


# Helper function to return value from the passed key
def get_configuration_value(keys):
    environment_list = []
    if settings.SKIP_ENV_VAR:
        # Get the configurations
        instance_configuration = InstanceConfiguration.objects.values("key", "value", "is_encrypted")

        for key in keys:
            for item in instance_configuration:
                if key.get("key") == item.get("key"):
                    if item.get("is_encrypted", False):
                        environment_list.append(decrypt_data(item.get("value")))
                    else:
                        environment_list.append(item.get("value"))

                    break
            else:
                environment_list.append(key.get("default"))
    else:
        # Get the configuration from os
        for key in keys:
            environment_list.append(os.environ.get(key.get("key"), key.get("default")))

    return tuple(environment_list)


SENDGRID_SMTP_HOST = "smtp.sendgrid.net"
SENDGRID_SMTP_PORT = "587"


def is_sendgrid_configured():
    return bool(os.environ.get("SENDGRID_API_KEY", "").strip())


def get_sendgrid_email_configuration():
    """SMTP settings for SendGrid: the API key is the password of the fixed "apikey" user."""
    from_email = os.environ.get("MAIL_FROM_EMAIL", "").strip()
    from_name = os.environ.get("MAIL_FROM_NAME", "").strip()
    sender = f"{from_name} <{from_email}>" if from_name and from_email else from_email
    return (
        SENDGRID_SMTP_HOST,
        "apikey",
        os.environ.get("SENDGRID_API_KEY", "").strip(),
        SENDGRID_SMTP_PORT,
        "1",  # STARTTLS
        "0",
        sender or os.environ.get("EMAIL_FROM", "HLIS Flow <no-reply@localhost>"),
    )


def get_email_configuration():
    # SendGrid credentials in the environment take precedence over the SMTP settings of God Mode
    if is_sendgrid_configured():
        return get_sendgrid_email_configuration()
    return get_configuration_value(
        [
            {"key": "EMAIL_HOST", "default": os.environ.get("EMAIL_HOST")},
            {"key": "EMAIL_HOST_USER", "default": os.environ.get("EMAIL_HOST_USER")},
            {
                "key": "EMAIL_HOST_PASSWORD",
                "default": os.environ.get("EMAIL_HOST_PASSWORD"),
            },
            {"key": "EMAIL_PORT", "default": os.environ.get("EMAIL_PORT", 587)},
            {"key": "EMAIL_USE_TLS", "default": os.environ.get("EMAIL_USE_TLS", "1")},
            {"key": "EMAIL_USE_SSL", "default": os.environ.get("EMAIL_USE_SSL", "0")},
            {
                "key": "EMAIL_FROM",
                "default": os.environ.get("EMAIL_FROM", "HLIS Flow <no-reply@localhost>"),
            },
        ]
    )
