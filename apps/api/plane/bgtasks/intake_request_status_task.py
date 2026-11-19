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
from plane.db.models import IntakeIssue, User
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception
from plane.utils.intake_form import STATUS_LABELS

# accepted, declined, duplicate: what the person who sent the request is told by email
EMAILED_STATUSES = {1, -1, 2}
STATUS_COLORS = {1: "#16a34a", -1: "#dc2626", 2: "#6b7280"}


def _name(user):
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.display_name or user.email


@shared_task
def intake_request_status(intake_issue_id, actor_id, portal_url):
    """Email the person who sent a request (its Created by) that the team accepted, declined (with the reason) or
    marked it as a duplicate."""
    try:
        intake_issue = (
            IntakeIssue.objects.select_related("issue", "project", "created_by", "duplicate_to")
            .filter(pk=intake_issue_id)
            .first()
        )
        if not intake_issue or intake_issue.status not in EMAILED_STATUSES:
            return
        client = intake_issue.created_by
        email = (client.email if client else "") or intake_issue.source_email
        if not email or (client and str(client.id) == str(actor_id)):
            return
        actor = User.objects.filter(pk=actor_id).first()
        project = intake_issue.project
        status_label = STATUS_LABELS.get(intake_issue.status, "Updated")
        if intake_issue.status == -1:
            note = f"Reason: {(intake_issue.extra or {}).get('decline_reason') or 'No reason given.'}"
        elif intake_issue.status == 2 and intake_issue.duplicate_to:
            note = f"It is the same as {project.identifier}-{intake_issue.duplicate_to.sequence_id}."
        else:
            note = "The team is working on it. Follow its progress under Work Items."
        context = {
            "client_name": _name(client) if client else email,
            "actor_name": _name(actor) if actor else "The team",
            "project_name": project.name,
            "key": f"{project.identifier}-{intake_issue.issue.sequence_id}",
            "title": intake_issue.issue.name,
            "status_label": status_label,
            "status_note": note,
            "status_color": STATUS_COLORS.get(intake_issue.status, "#6b7280"),
            "portal_url": portal_url,
        }
        html_content = render_to_string("emails/notifications/intake_request_status.html", context)
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
            subject=f"Your request {context['key']} was {status_label.lower()} — {project.name}",
            body=text_content,
            from_email=EMAIL_FROM,
            to=[email],
            connection=connection,
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        logging.getLogger("plane.worker").info("Intake request status email sent.")
    except Exception as e:
        log_exception(e)
        return
