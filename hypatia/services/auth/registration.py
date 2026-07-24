"""Register new users with a matching Profile row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from hypatia.extensions import db
from hypatia.models import Profile, User
from hypatia.services.audit import record_account_event
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_ACTIVE,
    EMAIL_ALREADY_REGISTERED_MESSAGE,
    EVENT_ACCOUNT_CREATED,
)
from hypatia.services.auth.emails import validate_email
from hypatia.services.auth.passwords import hash_password
from hypatia.services.auth.sessions import create_session
from hypatia.services.auth.validation import validate_password

MAX_NAME_LENGTH = 128


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    ok: bool
    error: str | None = None
    conflict: bool = False
    user: User | None = None
    raw_token: str | None = None


def _validate_name(value: str, field_name: str) -> tuple[str | None, str | None]:
    trimmed = value.strip()
    if not trimmed:
        return None, f"{field_name} is required"
    if len(trimmed) > MAX_NAME_LENGTH:
        return None, f"{field_name} must be at most {MAX_NAME_LENGTH} characters"
    return trimmed, None


def _email_already_registered(normalized_email: str) -> bool:
    existing = db.session.scalar(
        select(User.id).where(func.lower(User.email) == normalized_email)
    )
    return existing is not None


def register_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    *,
    ip_address: str | None = None,
    request_id: str | None = None,
    user_agent: str | None = None,
) -> RegistrationResult:
    """Create User + Profile + session atomically and return the raw session token.

    Decision: emit ``ACCOUNT_CREATED`` only. Automatic post-registration login uses the
    session system but is not recorded as ``LOGIN_SUCCESS``, to avoid duplicate
    semantic events for a single registration action.
    """
    email_result = validate_email(email)
    if not email_result.ok or email_result.normalized is None:
        return RegistrationResult(ok=False, error=email_result.error)

    password_result = validate_password(password)
    if not password_result.ok:
        return RegistrationResult(ok=False, error=password_result.error)

    trimmed_first, first_error = _validate_name(first_name, "first_name")
    if first_error is not None or trimmed_first is None:
        return RegistrationResult(ok=False, error=first_error)

    trimmed_last, last_error = _validate_name(last_name, "last_name")
    if last_error is not None or trimmed_last is None:
        return RegistrationResult(ok=False, error=last_error)

    normalized_email = email_result.normalized
    if _email_already_registered(normalized_email):
        return RegistrationResult(
            ok=False,
            error=EMAIL_ALREADY_REGISTERED_MESSAGE,
            conflict=True,
        )

    now = _utcnow()
    try:
        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            # email_verified stays False until verification is implemented.
            # Do not block registration-created sessions on email_verified yet.
            email_verified=False,
            account_status=ACCOUNT_STATUS_ACTIVE,
            last_login_at=None,
            password_changed_at=now,
        )
        db.session.add(user)
        db.session.flush()

        db.session.add(
            Profile(
                user_id=user.id,
                first_name=trimmed_first,
                last_name=trimmed_last,
            )
        )
        record_account_event(
            user,
            EVENT_ACCOUNT_CREATED,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
        raw_token, _session = create_session(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return RegistrationResult(
            ok=False,
            error=EMAIL_ALREADY_REGISTERED_MESSAGE,
            conflict=True,
        )
    except Exception:
        db.session.rollback()
        raise

    return RegistrationResult(ok=True, user=user, raw_token=raw_token)
