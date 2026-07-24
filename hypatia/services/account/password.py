"""Change-password flow for the authenticated current user.

Security notification email ("your password was changed") is intentionally not
sent here: email-delivery infrastructure is not built yet. When email is
introduced, emit a notification after a successful PASSWORD_CHANGED commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from hypatia.extensions import db
from hypatia.models import AccountEvent, Session, User
from hypatia.services.auth.constants import EVENT_PASSWORD_CHANGED
from hypatia.services.auth.passwords import hash_password, verify_password
from hypatia.services.auth.sessions import create_session, revoke_all_sessions_for_user
from hypatia.services.auth.validation import validate_password

CURRENT_PASSWORD_INCORRECT_MESSAGE = "Current password is incorrect"
NEW_PASSWORDS_DO_NOT_MATCH_MESSAGE = "New passwords do not match"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize DB timestamps (SQLite may return naive UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso8601(value: datetime) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat()


@dataclass(frozen=True, slots=True)
class ChangePasswordResult:
    ok: bool
    error: str | None = None
    raw_token: str | None = None
    password_changed_at: str | None = None


def _record_password_changed(*, user_id, ip_address: str | None) -> None:
    db.session.add(
        AccountEvent(
            user_id=user_id,
            event_type=EVENT_PASSWORD_CHANGED,
            ip_address=ip_address,
        )
    )


def change_user_password(
    user: User,
    current_session: Session,
    *,
    current_password: str,
    new_password: str,
    confirm_new_password: str,
    ip_address: str | None = None,
) -> ChangePasswordResult:
    """Verify the current password, set a new one, and rotate all sessions.

    Identity comes from ``user`` / ``current_session`` (authenticated request
    context), never from client-supplied user ids. On success: update hash,
    set ``password_changed_at``, revoke all sessions (including
    ``current_session``), create one replacement session, and record
    ``PASSWORD_CHANGED`` — all in one database transaction.
    """
    if current_session.user_id != user.id:
        raise ValueError("current_session does not belong to user")

    if not verify_password(user.password_hash, current_password):
        return ChangePasswordResult(ok=False, error=CURRENT_PASSWORD_INCORRECT_MESSAGE)

    if new_password != confirm_new_password:
        return ChangePasswordResult(ok=False, error=NEW_PASSWORDS_DO_NOT_MATCH_MESSAGE)

    password_result = validate_password(new_password)
    if not password_result.ok:
        return ChangePasswordResult(ok=False, error=password_result.error)

    now = _utcnow()
    try:
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        revoke_all_sessions_for_user(user)
        raw_token, _new_session = create_session(user)
        _record_password_changed(user_id=user.id, ip_address=ip_address)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return ChangePasswordResult(
        ok=True,
        raw_token=raw_token,
        password_changed_at=_iso8601(now),
    )
