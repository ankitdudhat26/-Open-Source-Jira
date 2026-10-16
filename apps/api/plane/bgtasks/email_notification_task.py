# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

# Third party imports
from celery import shared_task
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

# Django imports
from django.conf import settings
from django.utils import timezone

# Module imports
from plane.db.models import EmailNotificationLog, Issue, User
from plane.license.utils.instance_value import get_email_configuration
from plane.settings.redis import redis_instance
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception
from plane.utils.work_item_email import build_work_item_email, get_brand_name, thread_headers


def remove_unwanted_characters(input_text):
    # Remove only control characters and potentially problematic characters for email subjects
    processed_text = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", input_text)
    return processed_text


# acquire and delete redis lock
def acquire_lock(lock_id, expire_time=300):
    redis_client = redis_instance()
    """Attempt to acquire a lock with a specified expiration time."""
    return redis_client.set(lock_id, "true", nx=True, ex=expire_time)


def release_lock(lock_id):
    """Release a lock."""
    redis_client = redis_instance()
    redis_client.delete(lock_id)


@shared_task
def stack_email_notification():
    # get all email notifications
    email_notifications = EmailNotificationLog.objects.filter(processed_at__isnull=True).order_by("receiver").values()

    # Create the below format for each of the issues
    # {"issue_id" : { "actor_id1": [ { data }, { data } ], "actor_id2": [ { data }, { data } ] }}

    # Convert to unique receivers list
    receivers = list(set([str(notification.get("receiver_id")) for notification in email_notifications]))
    processed_notifications = []
    # Loop through all the issues to create the emails
    for receiver_id in receivers:
        # Notification triggered for the receiver
        receiver_notifications = [
            notification for notification in email_notifications if str(notification.get("receiver_id")) == receiver_id
        ]
        # create payload for all issues
        payload = {}
        email_notification_ids = {}
        for receiver_notification in receiver_notifications:
            issue_key = receiver_notification.get("entity_identifier")
            payload.setdefault(issue_key, {}).setdefault(str(receiver_notification.get("triggered_by_id")), []).append(
                receiver_notification.get("data")
            )
            # append processed notifications
            processed_notifications.append(receiver_notification.get("id"))
            # the logs of each work item are marked sent by that work item's email only
            email_notification_ids.setdefault(issue_key, []).append(receiver_notification.get("id"))

        # Create emails for all the issues
        for issue_id, notification_data in payload.items():
            send_email_notification.delay(
                issue_id=issue_id,
                notification_data=notification_data,
                receiver_id=receiver_id,
                email_notification_ids=email_notification_ids[issue_id],
            )

    # Update the email notification log
    EmailNotificationLog.objects.filter(pk__in=processed_notifications).update(processed_at=timezone.now())


def create_payload(notification_data):
    # return format {"actor_id":  { "key": { "old_value": [], "new_value": [] } }}
    data = {}
    for actor_id, changes in notification_data.items():
        for change in changes:
            issue_activity = change.get("issue_activity")
            if issue_activity:  # Ensure issue_activity is not None
                field = issue_activity.get("field")
                old_value = str(issue_activity.get("old_value"))
                new_value = str(issue_activity.get("new_value"))

                # Append old_value if it's not empty and not already in the list
                if old_value:
                    (
                        data.setdefault(actor_id, {})
                        .setdefault(field, {})
                        .setdefault("old_value", [])
                        .append(old_value)
                        if old_value not in data.setdefault(actor_id, {}).setdefault(field, {}).get("old_value", [])
                        else None
                    )

                # Append new_value if it's not empty and not already in the list
                if new_value:
                    (
                        data.setdefault(actor_id, {})
                        .setdefault(field, {})
                        .setdefault("new_value", [])
                        .append(new_value)
                        if new_value not in data.setdefault(actor_id, {}).setdefault(field, {}).get("new_value", [])
                        else None
                    )

                if not data.get("actor_id", {}).get("activity_time", False):
                    data[actor_id]["activity_time"] = str(
                        datetime.fromisoformat(issue_activity.get("activity_time").rstrip("Z")).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )

    return data


def process_mention(mention_component):
    soup = BeautifulSoup(mention_component, "html.parser")
    mentions = soup.find_all("mention-component")
    for mention in mentions:
        user_id = mention["entity_identifier"]
        user = User.objects.get(pk=user_id)
        user_name = user.display_name
        highlighted_name = f"@{user_name}"
        mention.replace_with(highlighted_name)
    return str(soup)


def process_html_content(content):
    if content is None:
        return None
    processed_content_list = []
    for html_content in content:
        processed_content = process_mention(html_content)
        processed_content_list.append(processed_content)
    return processed_content_list


@shared_task
def send_email_notification(issue_id, notification_data, receiver_id, email_notification_ids):
    # Convert UUIDs to a sorted, concatenated string
    sorted_ids = sorted(email_notification_ids)
    ids_str = "_".join(str(id) for id in sorted_ids)
    lock_id = f"send_email_notif_{issue_id}_{receiver_id}_{ids_str}"

    # acquire the lock for sending emails
    try:
        if acquire_lock(lock_id=lock_id):
            # get the redis instance
            ri = redis_instance()
            base_api = ri.get(str(issue_id)).decode() if ri.get(str(issue_id)) else None
            # The request origin is kept in redis for 10 minutes and is missing for changes made through the
            # public API, so fall back to the configured app url instead of dropping the watchers' email
            if not base_api:
                base_api = (settings.APP_BASE_URL or settings.WEB_URL or "").rstrip("/") or None

            # Skip if base api is not present
            if not base_api:
                return

            # Get email configurations
            (
                EMAIL_HOST,
                EMAIL_HOST_USER,
                EMAIL_HOST_PASSWORD,
                EMAIL_PORT,
                EMAIL_USE_TLS,
                EMAIL_USE_SSL,
                EMAIL_FROM,
            ) = get_email_configuration()

            receiver = User.objects.get(pk=receiver_id)
            issue = Issue.objects.select_related(
                "project", "project__workspace", "state", "type", "parent", "milestone"
            ).get(pk=issue_id)
            email = build_work_item_email(
                issue=issue,
                receiver=receiver,
                notification_data=notification_data,
                base_url=base_api.rstrip("/"),
                brand=get_brand_name(),
            )
            if email is None:
                release_lock(lock_id=lock_id)
                return
            subject = remove_unwanted_characters(email["subject"])
            html_content = render_to_string("emails/notifications/work-item-updates.html", email["context"])
            text_content = generate_plain_text_from_html(html_content)

            try:
                connection = get_connection(
                    host=EMAIL_HOST,
                    port=int(EMAIL_PORT),
                    username=EMAIL_HOST_USER,
                    password=EMAIL_HOST_PASSWORD,
                    use_tls=EMAIL_USE_TLS == "1",
                    use_ssl=EMAIL_USE_SSL == "1",
                )

                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_content,
                    from_email=EMAIL_FROM,
                    to=[receiver.email],
                    connection=connection,
                    # all emails about one work item form one conversation in the mail client
                    headers=thread_headers(issue, EMAIL_FROM),
                )
                msg.attach_alternative(html_content, "text/html")
                msg.send()
                logging.getLogger("plane.worker").info("Email Sent Successfully")

                # Update the logs
                EmailNotificationLog.objects.filter(pk__in=email_notification_ids).update(sent_at=timezone.now())

                # release the lock
                release_lock(lock_id=lock_id)
                return
            except Exception as e:
                log_exception(e)
                # release the lock
                release_lock(lock_id=lock_id)
                return
        else:
            logging.getLogger("plane.worker").info("Duplicate email received skipping")
            return
    except (Issue.DoesNotExist, User.DoesNotExist):
        release_lock(lock_id=lock_id)
        return
    except Exception as e:
        log_exception(e)
        release_lock(lock_id=lock_id)
        return
