# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""One click "Stop watching" from a notification email, like Jira.

The link carries a signed token (user + work item), so it works without signing in. Opening the link only shows
a confirmation page; the watch is removed when the button is pressed, because mail scanners open links on their
own and must not unsubscribe anyone.
"""

from django.core import signing
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from plane.db.models import Issue, IssueSubscriber

UNWATCH_SALT = "plane.work-item.unwatch"
# links in old emails stop working after this many days
UNWATCH_MAX_AGE = 60 * 60 * 24 * 90


def make_unwatch_token(user_id, issue_id):
    return signing.dumps({"u": str(user_id), "i": str(issue_id)}, salt=UNWATCH_SALT, compress=True)


def read_unwatch_token(token):
    try:
        data = signing.loads(token, salt=UNWATCH_SALT, max_age=UNWATCH_MAX_AGE)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or not data.get("u") or not data.get("i"):
        return None
    return data


def _page(title, message, button=False, status=200):
    form = (
        '<form method="post"><button type="submit" style="margin-top:16px;padding:8px 16px;border:0;'
        'border-radius:3px;background:#0052cc;color:#fff;font-size:14px;font-weight:600;cursor:pointer">'
        "Stop watching</button></form>"
        if button
        else ""
    )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title></head>"
        '<body style="margin:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,'
        'Helvetica,Arial,sans-serif;color:#172b4d">'
        '<div style="max-width:480px;margin:64px auto;padding:24px;background:#fff;border:1px solid #dfe1e6;'
        'border-radius:6px">'
        f'<h1 style="margin:0 0 8px;font-size:20px">{escape(title)}</h1>'
        f'<p style="margin:0;font-size:14px;line-height:21px">{escape(message)}</p>{form}</div></body></html>'
    )
    return HttpResponse(html, status=status, content_type="text/html; charset=utf-8")


@method_decorator(csrf_exempt, name="dispatch")
class UnwatchWorkItemEndpoint(View):
    def _load(self, token):
        data = read_unwatch_token(token)
        if data is None:
            return None, None
        issue = Issue.all_objects.select_related("project").filter(pk=data["i"]).first()
        return data, issue

    def get(self, request, token):
        data, issue = self._load(token)
        if data is None or issue is None:
            return _page(
                "Link expired", "This link is no longer valid. Open the work item to stop watching it.", status=400
            )
        key = f"{issue.project.identifier}-{issue.sequence_id}"
        if not IssueSubscriber.objects.filter(issue_id=issue.id, subscriber_id=data["u"]).exists():
            return _page("Not watching", f"You are not watching {key} {issue.name}.")
        return _page(
            f"Stop watching {key}?",
            f"You will no longer get emails about {key} {issue.name}.",
            button=True,
        )

    def post(self, request, token):
        data, issue = self._load(token)
        if data is None or issue is None:
            return _page(
                "Link expired", "This link is no longer valid. Open the work item to stop watching it.", status=400
            )
        IssueSubscriber.objects.filter(issue_id=issue.id, subscriber_id=data["u"]).delete()
        key = f"{issue.project.identifier}-{issue.sequence_id}"
        return _page(
            "You stopped watching",
            f"You will no longer get emails about {key} {issue.name}. "
            "You will start watching it again if you are assigned to it, mentioned or comment on it.",
        )
