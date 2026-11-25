# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib
import secrets

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .base import BaseModel

TOKEN_PREFIX = "hlx_"


def hash_token(token):
    """Only a SHA-256 hash of a token is stored: a leaked database row cannot be used to log in."""
    return hashlib.sha256(str(token).encode()).hexdigest()


def password_fingerprint(user):
    """Changes when the user's password changes (or is reset): every token issued before stops working."""
    return hashlib.sha256(f"{user.pk}:{user.password}".encode()).hexdigest()


def new_token():
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(40)}"


class ExternalApiSession(BaseModel):
    """A login to the external (read-only) API at /api/ext/v1/ with email and password.

    Kept apart from the API tokens of a user's settings (plane.db.models.APIToken), so those lists and their behaviour
    do not change. The client sends the token it got at login as ``Authorization: Bearer <token>``.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="external_api_sessions")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    # the first characters of the token, to recognise a session without storing the token
    token_hint = models.CharField(max_length=16, blank=True, default="")
    # the password the session was opened with (see password_fingerprint): a new password ends the session
    password_fingerprint = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    ip_address = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "External API Session"
        verbose_name_plural = "External API Sessions"
        db_table = "external_api_sessions"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user_id} {self.token_hint}…"
