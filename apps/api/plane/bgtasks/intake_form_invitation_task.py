# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging

# Third party imports
from celery import shared_task

# Django imports
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

# Module imports
from plane.db.models import Project, User
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception


@shared_task
def intake_form_invitation(email, project_id, form_url, invitor_id):
    """Email a client the link of a project's request form, where they log in to send requests."""
    try:
        invitor = User.objects.get(pk=invitor_id)
        project = Project.objects.get(pk=project_id)
        name = invitor.first_name or invitor.display_name or invitor.email
        subject = f"{name} invited you to send requests to {project.name} on HLIS Flow"
        html_content = render_to_string(
            "emails/invitations/intake_form_invitation.html",
            {
                "email": email,
                "first_name": name,
                "project_name": project.name,
                "invitation_url": form_url,
                "current_site": form_url,
            },
        )
        text_content = generate_plain_text_from_html(html_content)

        (
            EMAIL_HOST,
            EMAIL_HOST_USER,
            EMAIL_HOST_PASSWORD,
            EMAIL_PORT,
            EMAIL_USE_TLS,
            EMAIL_USE_SSL,
            EMAIL_FROM,
        ) = get_email_configuration()
        connection = get_connection(
            host=EMAIL_HOST,
            port=int(EMAIL_PORT),
            username=EMAIL_HOST_USER,
            password=EMAIL_HOST_PASSWORD,
            use_tls=EMAIL_USE_TLS == "1",
            use_ssl=EMAIL_USE_SSL == "1",
        )
        msg = EmailMultiAlternatives(
            subject=subject, body=text_content, from_email=EMAIL_FROM, to=[email], connection=connection
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        logging.getLogger("plane.worker").info("Intake form invitation sent.")
    except Exception as e:
        log_exception(e)
        return
