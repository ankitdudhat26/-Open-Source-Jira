# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta

# Django imports
from django.utils import timezone

# Third party imports
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import SimpleRateThrottle

# Module imports
from plane.db.models import ExternalApiSession
from plane.db.models.external_api import hash_token, password_fingerprint

# how long a login lasts
SESSION_LIFETIME = timedelta(days=30)
# last_used_at is written at most this often (not on every request)
LAST_USED_RESOLUTION = timedelta(minutes=1)


class ExternalApiAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer <token>`` with the token from POST /api/ext/v1/auth/login/."""

    keyword = "Bearer"

    def authenticate_header(self, request):
        # makes DRF answer 401 (not 403) without a valid token
        return f'{self.keyword} realm="ext-api"'

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        parts = header.split()
        if not parts or parts[0] != self.keyword:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Send the header as: Authorization: Bearer <token>.")
        session = (
            ExternalApiSession.objects.select_related("user")
            .filter(token_hash=hash_token(parts[1]), revoked_at__isnull=True, expires_at__gt=timezone.now())
            .first()
        )
        if (
            session is None
            or not session.user.is_active
            or session.user.is_bot
            # the password was changed or reset after this login
            or session.password_fingerprint != password_fingerprint(session.user)
        ):
            raise AuthenticationFailed("The token is not valid or has expired. Log in again.")
        now = timezone.now()
        if not session.last_used_at or now - session.last_used_at > LAST_USED_RESOLUTION:
            ExternalApiSession.objects.filter(pk=session.pk).update(last_used_at=now)
        return (session.user, session)


def client_ip(request):
    """The address of the client as the proxy saw it.

    The proxy (Caddy) appends the address it received the request from to X-Forwarded-For, so the last entry is the real
    one; the first entries come from the client and can be anything. Without the header (no proxy, e.g. local), the
    socket address."""
    forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
    return (forwarded[-1] if forwarded else request.META.get("REMOTE_ADDR", ""))[:64]


class LoginRateThrottle(SimpleRateThrottle):
    """At most 10 login attempts a minute from one IP address (wrong passwords included)."""

    scope = "ext_api_login"
    rate = "10/minute"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": client_ip(request)}


# failed logins for one account: after this many in the window, the account's logins are refused until it ends
ACCOUNT_FAILURE_LIMIT = 10
ACCOUNT_FAILURE_WINDOW = 15 * 60


class ExternalApiRateThrottle(SimpleRateThrottle):
    """At most 300 requests a minute for one logged-in user."""

    scope = "ext_api"
    rate = "300/minute"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(request.user.pk)}
