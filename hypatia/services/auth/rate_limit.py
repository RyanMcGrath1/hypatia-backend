"""Authentication rate-limit helpers (Flask-Limiter keyfuncs and limit strings).

Per-account Login buckets use a HMAC of the *normalized* email so unknown and
known addresses share the same mechanism without storing plaintext email as a
limiter key. Client IP keys use Flask's ``request.remote_addr`` (do not trust
spoofable ``X-Forwarded-For`` unless a trusted-proxy setup is configured).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid

from flask import current_app, g, has_request_context, request
from sqlalchemy import select

from hypatia.extensions import db
from hypatia.models import MfaLoginChallenge
from hypatia.services.auth.emails import normalize_email
from hypatia.services.auth.mfa_challenge import hash_mfa_challenge_token

_security_logger = logging.getLogger("hypatia.security")

AUTH_RATE_LIMITED_MESSAGE = (
    "Too many authentication attempts. Please try again later."
)


def _limit_string(
    count_key: str,
    window_key: str,
    *,
    default_count: int,
    default_window: int,
) -> str:
    count = max(int(current_app.config.get(count_key, default_count)), 1)
    window = max(int(current_app.config.get(window_key, default_window)), 1)
    return f"{count} per {window} minutes"


def login_account_limit_string() -> str:
    return _limit_string(
        "AUTH_LOGIN_ACCOUNT_LIMIT",
        "AUTH_LOGIN_ACCOUNT_WINDOW_MINUTES",
        default_count=10,
        default_window=15,
    )


def login_ip_limit_string() -> str:
    return _limit_string(
        "AUTH_LOGIN_IP_LIMIT",
        "AUTH_LOGIN_IP_WINDOW_MINUTES",
        default_count=30,
        default_window=15,
    )


def totp_account_limit_string() -> str:
    return _limit_string(
        "AUTH_TOTP_ACCOUNT_LIMIT",
        "AUTH_TOTP_ACCOUNT_WINDOW_MINUTES",
        default_count=10,
        default_window=15,
    )


def totp_ip_limit_string() -> str:
    return _limit_string(
        "AUTH_TOTP_IP_LIMIT",
        "AUTH_TOTP_IP_WINDOW_MINUTES",
        default_count=30,
        default_window=15,
    )


def _hmac_hex(material: str) -> str:
    secret = current_app.config.get("SECRET_KEY") or ""
    if isinstance(secret, bytes):
        key = secret
    else:
        key = str(secret).encode("utf-8")
    return hmac.new(key, material.encode("utf-8"), hashlib.sha256).hexdigest()


def login_account_rate_limit_key() -> str:
    """Pseudonymous per-account Login key from normalized email (no DB lookup)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("email"), str):
        return "login-account:invalid"
    normalized = normalize_email(data["email"])
    if not normalized:
        return "login-account:invalid"
    return f"login-account:{_hmac_hex(normalized)}"


def totp_account_rate_limit_key() -> str:
    """Per-user TOTP key after resolving challenge → user_id (never raw token).

    Unknown/malformed challenge tokens map to a HMAC of the token hash so the
    raw challenge token is never used as a storage key. Resolved challenges use
    ``user_id`` so replacing Challenge A with Challenge B does not reset the
    account-level TOTP bucket.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("challenge_token"), str):
        return "totp-account:invalid"

    raw_token = data["challenge_token"]
    if not raw_token:
        return "totp-account:invalid"

    token_hash = hash_mfa_challenge_token(raw_token)
    challenge = db.session.scalar(
        select(MfaLoginChallenge).where(MfaLoginChallenge.token_hash == token_hash)
    )
    if challenge is None:
        return f"totp-account:unresolved:{_hmac_hex(token_hash)}"

    user_id = challenge.user_id
    if isinstance(user_id, uuid.UUID):
        return f"totp-account:user:{user_id}"
    return f"totp-account:user:{user_id}"


def log_auth_rate_limited(*, category: str) -> None:
    """Safe security log for a rate-limit breach (no emails/tokens/keys)."""
    request_id = None
    ip_address = None
    endpoint = None
    if has_request_context():
        raw = getattr(g, "request_id", None)
        request_id = raw if isinstance(raw, str) and raw else None
        ip_address = request.remote_addr
        endpoint = request.endpoint

    _security_logger.info(
        "security_event event_type=AUTH_RATE_LIMITED category=%s",
        category,
        extra={
            "event": "security_event",
            "event_type": "AUTH_RATE_LIMITED",
            "category": category,
            "endpoint": endpoint,
            "request_id": request_id,
            "ip_address": ip_address,
        },
    )
