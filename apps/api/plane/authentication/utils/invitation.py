# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Sign up is by invitation only: an email can make an account only after an admin invited it (to a workspace, or
to a project's request form). Whatever the instance's ENABLE_SIGNUP setting says."""

# Module imports
from plane.authentication.adapter.error import AUTHENTICATION_ERROR_CODES, AuthenticationException
from plane.db.models import IntakeFormInvite, User, WorkspaceMemberInvite


def has_signup_invitation(email):
    email = (email or "").strip()
    return bool(email) and (
        WorkspaceMemberInvite.objects.filter(email__iexact=email).exists()
        or IntakeFormInvite.objects.filter(email__iexact=email).exists()
    )


def signup_not_invited(email):
    """The error for an email that has no account and no invitation (it may not sign up), else None."""
    if User.objects.filter(email__iexact=email).exists() or has_signup_invitation(email):
        return None
    return AuthenticationException(
        error_code=AUTHENTICATION_ERROR_CODES["SIGNUP_DISABLED"],
        error_message="SIGNUP_DISABLED",
        payload={"email": email},
    )
