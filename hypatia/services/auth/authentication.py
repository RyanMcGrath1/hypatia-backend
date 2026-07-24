"""Authenticate users by email and password (with optional TOTP MFA deferral)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from hypatia.extensions import db
from hypatia.models import User
from hypatia.services.audit import log_security_event, record_account_event
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_ACTIVE,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCESS,
)
from hypatia.services.auth.emails import normalize_email
from hypatia.services.auth.passwords import hash_password, password_needs_rehash, verify_password
from hypatia.services.security.totp import user_has_totp_enabled


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    success: bool
    user: User | None = None
    mfa_required: bool = False


def _find_user_by_email(email: str) -> User | None:
    normalized = normalize_email(email)
    return db.session.scalar(select(User).where(func.lower(User.email) == normalized))


def authenticate_user(
    email: str,
    password: str,
    *,
    ip_address: str | None = None,
    request_id: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> AuthenticationResult:
    """Authenticate by email/password. Failures do not reveal whether the email exists.

    When the user has TOTP enabled, password success alone is not a completed
    login: ``LOGIN_SUCCESS`` and ``last_login_at`` are deferred until MFA
    succeeds. Argon2 maintenance rehash may still occur on password success.

    Unknown-email failures are logged via ``hypatia.security`` (no ``AccountEvent``)
    so attempted emails are never stored in audit rows.

    Decision: do not gate login on ``email_verified`` until email verification exists.
    An ``email_verified`` check may be added here when that feature is implemented.
    """
    user = _find_user_by_email(email)
    if user is None:
        log_security_event(
            EVENT_LOGIN_FAILED,
            ip_address=ip_address,
            request_id=request_id,
        )
        return AuthenticationResult(success=False)

    if user.account_status != ACCOUNT_STATUS_ACTIVE:
        record_account_event(
            user,
            EVENT_LOGIN_FAILED,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
        db.session.commit()
        return AuthenticationResult(success=False)

    if not verify_password(user.password_hash, password):
        record_account_event(
            user,
            EVENT_LOGIN_FAILED,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
        db.session.commit()
        return AuthenticationResult(success=False)

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    if user_has_totp_enabled(user):
        # Password OK but MFA still required — do not issue LOGIN_SUCCESS or
        # update last_login_at yet.
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return AuthenticationResult(success=True, user=user, mfa_required=True)

    user.last_login_at = _utcnow()
    record_account_event(
        user,
        EVENT_LOGIN_SUCCESS,
        ip_address=ip_address,
        request_id=request_id,
        user_agent=user_agent,
    )
    if commit:
        db.session.commit()
    else:
        db.session.flush()

    return AuthenticationResult(success=True, user=user, mfa_required=False)
