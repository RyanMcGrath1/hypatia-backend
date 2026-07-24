"""Authenticate users by email and password."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from hypatia.extensions import db
from hypatia.models import AccountEvent, User
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_ACTIVE,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCESS,
)
from hypatia.services.auth.passwords import hash_password, password_needs_rehash, verify_password


def normalize_email_for_lookup(email: str) -> str:
    """Normalize email for lookup (strip + casefold). Registration must use the same rule."""
    return email.strip().casefold()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    success: bool
    user: User | None = None


def _find_user_by_email(email: str) -> User | None:
    normalized = normalize_email_for_lookup(email)
    return db.session.scalar(select(User).where(func.lower(User.email) == normalized))


def _record_account_event(
    *,
    user_id,
    event_type: str,
    ip_address: str | None,
) -> None:
    db.session.add(
        AccountEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
        )
    )


def authenticate_user(
    email: str,
    password: str,
    *,
    ip_address: str | None = None,
    commit: bool = True,
) -> AuthenticationResult:
    """Authenticate by email/password. Failures do not reveal whether the email exists."""
    user = _find_user_by_email(email)
    if user is None:
        return AuthenticationResult(success=False)

    if user.account_status != ACCOUNT_STATUS_ACTIVE:
        _record_account_event(
            user_id=user.id,
            event_type=EVENT_LOGIN_FAILED,
            ip_address=ip_address,
        )
        db.session.commit()
        return AuthenticationResult(success=False)

    if not verify_password(user.password_hash, password):
        _record_account_event(
            user_id=user.id,
            event_type=EVENT_LOGIN_FAILED,
            ip_address=ip_address,
        )
        db.session.commit()
        return AuthenticationResult(success=False)

    user.last_login_at = _utcnow()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    _record_account_event(
        user_id=user.id,
        event_type=EVENT_LOGIN_SUCCESS,
        ip_address=ip_address,
    )
    if commit:
        db.session.commit()
    else:
        db.session.flush()

    return AuthenticationResult(success=True, user=user)
