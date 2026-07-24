"""Short-lived MFA login challenges after password verification.

Challenge tokens use the same opacity standard as Session tokens
(``secrets.token_urlsafe(32)`` + SHA-256 hash storage) but are never valid as
authenticated Session tokens.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select

from hypatia.extensions import db
from hypatia.models import MfaLoginChallenge, User
from hypatia.services.audit import record_account_event
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_ACTIVE,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCESS,
    INVALID_CREDENTIALS_MESSAGE,
)
from hypatia.services.auth.sessions import TOKEN_RANDOM_BYTES, create_session
from hypatia.services.security.totp import user_has_totp_enabled
from hypatia.services.security.totp_crypto import TotpEncryptionError, decrypt_totp_secret
from hypatia.services.security.totp_verify import verify_totp_code

GENERIC_AUTH_FAILURE_MESSAGE = INVALID_CREDENTIALS_MESSAGE


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def generate_mfa_challenge_token() -> str:
    return secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def hash_mfa_challenge_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _challenge_ttl() -> timedelta:
    minutes = int(current_app.config.get("TOTP_LOGIN_CHALLENGE_TTL_MINUTES", 5))
    return timedelta(minutes=max(minutes, 1))


def _max_attempts() -> int:
    return max(int(current_app.config.get("TOTP_LOGIN_MAX_ATTEMPTS", 5)), 1)


def create_mfa_login_challenge(user: User) -> str:
    """Create an MFA challenge row and return the raw token (caller commits)."""
    now = _utcnow()
    raw_token = generate_mfa_challenge_token()
    challenge = MfaLoginChallenge(
        user_id=user.id,
        token_hash=hash_mfa_challenge_token(raw_token),
        created_at=now,
        expires_at=now + _challenge_ttl(),
        attempt_count=0,
        consumed_at=None,
    )
    db.session.add(challenge)
    return raw_token


def delete_mfa_login_challenges_for_user(user_id) -> None:
    """Delete all MFA login challenges for ``user_id`` (caller commits).

    Used when credentials change or the account is deleted so outstanding
    pre-authentication challenges cannot be completed afterward. Already
    consumed or expired rows are removed harmlessly.
    """
    rows = db.session.scalars(
        select(MfaLoginChallenge).where(MfaLoginChallenge.user_id == user_id)
    ).all()
    for row in rows:
        db.session.delete(row)


@dataclass(frozen=True, slots=True)
class CompleteTotpLoginResult:
    ok: bool
    error: str | None = None
    raw_token: str | None = None


def complete_totp_login(
    *,
    challenge_token: str,
    code: str,
    ip_address: str | None = None,
    request_id: str | None = None,
    user_agent: str | None = None,
) -> CompleteTotpLoginResult:
    """Complete MFA login using a challenge token + TOTP code.

    Failures return a generic authentication error and never reveal challenge
    or TOTP state details.
    """
    token_hash = hash_mfa_challenge_token(challenge_token)
    challenge = db.session.scalar(
        select(MfaLoginChallenge).where(MfaLoginChallenge.token_hash == token_hash)
    )
    if challenge is None:
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)

    now = _utcnow()
    if challenge.consumed_at is not None:
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)
    if _as_utc(challenge.expires_at) <= now:
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)
    if challenge.attempt_count >= _max_attempts():
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)

    user = challenge.user
    if user is None or user.account_status != ACCOUNT_STATUS_ACTIVE:
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)

    method = user.totp_method
    if method is None or not method.enabled:
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)

    try:
        secret = decrypt_totp_secret(method.secret_encrypted)
    except TotpEncryptionError:
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)

    verification = verify_totp_code(
        secret,
        code,
        last_used_timecode=method.last_used_timecode,
    )
    if not verification.ok or verification.matched_timecode is None:
        challenge.attempt_count += 1
        record_account_event(
            user,
            EVENT_LOGIN_FAILED,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return CompleteTotpLoginResult(ok=False, error=GENERIC_AUTH_FAILURE_MESSAGE)

    try:
        challenge.consumed_at = now
        method.last_used_timecode = verification.matched_timecode
        user.last_login_at = now
        record_account_event(
            user,
            EVENT_LOGIN_SUCCESS,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
        raw_token, _session = create_session(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return CompleteTotpLoginResult(ok=True, raw_token=raw_token)


# Re-export helper used by authentication/login for clarity.
__all__ = [
    "GENERIC_AUTH_FAILURE_MESSAGE",
    "CompleteTotpLoginResult",
    "complete_totp_login",
    "create_mfa_login_challenge",
    "delete_mfa_login_challenges_for_user",
    "generate_mfa_challenge_token",
    "hash_mfa_challenge_token",
    "user_has_totp_enabled",
]
