"""Opaque server-side session token lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select

from hypatia.extensions import db
from hypatia.models import Session, User
from hypatia.services.auth.constants import ACCOUNT_STATUS_ACTIVE

TOKEN_RANDOM_BYTES = 32
# Persist last_active_at at most once per interval to limit write load on hot sessions.
LAST_ACTIVE_UPDATE_INTERVAL = timedelta(minutes=15)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize DB timestamps for comparisons (SQLite may return naive UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def generate_session_token() -> str:
    """Return a new unpredictable opaque session token (never stored in the database)."""
    return secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def hash_session_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest stored for ``raw_token``."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _session_ttl() -> timedelta:
    days = int(current_app.config.get("AUTH_SESSION_TTL_DAYS", 30))
    return timedelta(days=max(days, 1))


@dataclass(frozen=True, slots=True)
class SessionValidationResult:
    valid: bool
    session: Session | None = None
    user: User | None = None


def create_session(user: User) -> tuple[str, Session]:
    """Create a session row and return ``(raw_token, session)`` (caller commits)."""
    now = _utcnow()
    raw_token = generate_session_token()
    session = Session(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        created_at=now,
        expires_at=now + _session_ttl(),
        last_active_at=now,
    )
    db.session.add(session)
    return raw_token, session


def get_session_from_token(raw_token: str) -> Session | None:
    """Return the session row for ``raw_token``, without validity checks."""
    token_hash = hash_session_token(raw_token)
    return db.session.scalar(select(Session).where(Session.token_hash == token_hash))


def _session_is_valid(session: Session, *, now: datetime | None = None) -> bool:
    current = _as_utc(now or _utcnow())
    if session.revoked_at is not None:
        return False
    if _as_utc(session.expires_at) <= current:
        return False
    user = session.user
    if user is None or user.account_status != ACCOUNT_STATUS_ACTIVE:
        return False
    return True


def _maybe_touch_last_active(session: Session, *, now: datetime | None = None) -> None:
    current = _as_utc(now or _utcnow())
    if current - _as_utc(session.last_active_at) >= LAST_ACTIVE_UPDATE_INTERVAL:
        session.last_active_at = current


def validate_session(raw_token: str) -> SessionValidationResult:
    """Validate ``raw_token`` and optionally refresh throttled ``last_active_at``."""
    session = get_session_from_token(raw_token)
    if session is None:
        return SessionValidationResult(valid=False)

    now = _utcnow()
    if not _session_is_valid(session, now=now):
        return SessionValidationResult(valid=False)

    _maybe_touch_last_active(session, now=now)
    return SessionValidationResult(valid=True, session=session, user=session.user)


def revoke_session(session: Session) -> None:
    """Mark ``session`` revoked (caller commits)."""
    session.revoked_at = _utcnow()


def revoke_all_sessions_for_user(user: User) -> None:
    """Revoke every non-revoked session for ``user`` (caller commits)."""
    sessions = db.session.scalars(
        select(Session).where(
            Session.user_id == user.id,
            Session.revoked_at.is_(None),
        )
    ).all()
    now = _utcnow()
    for session in sessions:
        session.revoked_at = now
