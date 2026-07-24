"""TOTP authenticator-app setup, enable, and disable.

Before this feature is production-complete, add an account-recovery mechanism
(e.g. recovery codes). Without recovery, a user who permanently loses their
authenticator device can be locked out. Do not weaken TOTP disable/login
rules to compensate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import current_app

from hypatia.extensions import db
from hypatia.models import AccountEvent, Session, TOTPMethod, User
from hypatia.services.auth.constants import EVENT_TOTP_DISABLED, EVENT_TOTP_ENABLED
from hypatia.services.auth.passwords import verify_password
from hypatia.services.auth.sessions import create_session, revoke_all_sessions_for_user
from hypatia.services.email import EmailDeliveryError, EmailNotConfiguredError, send_email
from hypatia.services.security.totp_crypto import (
    TotpEncryptionError,
    decrypt_totp_secret,
    encrypt_totp_secret,
)
from hypatia.services.security.totp_verify import (
    build_provisioning_uri,
    generate_totp_secret,
    verify_totp_code,
)

logger = logging.getLogger(__name__)

CURRENT_PASSWORD_INCORRECT_MESSAGE = "Current password is incorrect"
TOTP_ALREADY_ENABLED_MESSAGE = "Authenticator app is already enabled"
TOTP_SETUP_REQUIRED_MESSAGE = "Authenticator app setup is required first"
TOTP_NOT_ENABLED_MESSAGE = "Authenticator app is not enabled"
TOTP_INVALID_CODE_MESSAGE = "Invalid authenticator code"
TOTP_CONFIGURATION_ERROR_MESSAGE = "Authenticator app is temporarily unavailable"

_ENABLE_NOTIFY_SUBJECT = "Authenticator app enabled on your Hypatia account"
_DISABLE_NOTIFY_SUBJECT = "Authenticator app disabled on your Hypatia account"
_ENABLE_NOTIFY_BODY = "An authenticator app was enabled on your Hypatia account."
_DISABLE_NOTIFY_BODY = (
    "Authenticator app authentication was disabled on your Hypatia account."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def user_has_totp_enabled(user: User) -> bool:
    method = user.totp_method
    return method is not None and bool(method.enabled)


@dataclass(frozen=True, slots=True)
class TotpSetupResult:
    ok: bool
    error: str | None = None
    provisioning_uri: str | None = None
    manual_entry_key: str | None = None


@dataclass(frozen=True, slots=True)
class TotpEnableResult:
    ok: bool
    error: str | None = None
    raw_token: str | None = None


@dataclass(frozen=True, slots=True)
class TotpDisableResult:
    ok: bool
    error: str | None = None
    raw_token: str | None = None


def _issuer_name() -> str:
    return str(current_app.config.get("TOTP_ISSUER_NAME", "Hypatia") or "Hypatia")


def _record_event(*, user_id, event_type: str, ip_address: str | None) -> None:
    db.session.add(
        AccountEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
        )
    )


def _send_security_notification(*, to_address: str, subject: str, text_body: str) -> None:
    try:
        send_email(to_address=to_address, subject=subject, text_body=text_body)
    except (EmailDeliveryError, EmailNotConfiguredError) as exc:
        logger.error(
            "TOTP security notification failed error_type=%s",
            type(exc).__name__,
        )


def setup_totp(
    user: User,
    *,
    current_password: str,
) -> TotpSetupResult:
    """Start or replace incomplete TOTP enrollment after password reauth."""
    if not verify_password(user.password_hash, current_password):
        return TotpSetupResult(ok=False, error=CURRENT_PASSWORD_INCORRECT_MESSAGE)

    existing = user.totp_method
    if existing is not None and existing.enabled:
        return TotpSetupResult(ok=False, error=TOTP_ALREADY_ENABLED_MESSAGE)

    plaintext_secret = generate_totp_secret()
    try:
        encrypted = encrypt_totp_secret(plaintext_secret)
    except TotpEncryptionError:
        logger.error("TOTP setup failed: encryption configuration error")
        return TotpSetupResult(ok=False, error=TOTP_CONFIGURATION_ERROR_MESSAGE)

    now = _utcnow()
    if existing is not None:
        db.session.delete(existing)
        db.session.flush()

    method = TOTPMethod(
        user_id=user.id,
        secret_encrypted=encrypted,
        enabled=False,
        created_at=now,
        verified_at=None,
        last_used_timecode=None,
    )
    db.session.add(method)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    uri = build_provisioning_uri(
        secret_base32=plaintext_secret,
        account_email=user.email,
        issuer=_issuer_name(),
    )
    return TotpSetupResult(
        ok=True,
        provisioning_uri=uri,
        manual_entry_key=plaintext_secret,
    )


def enable_totp(
    user: User,
    current_session: Session,
    *,
    code: str,
    ip_address: str | None = None,
) -> TotpEnableResult:
    """Confirm pending TOTP setup, enable MFA, and rotate sessions."""
    if current_session.user_id != user.id:
        raise ValueError("current_session does not belong to user")

    method = user.totp_method
    if method is None or method.enabled:
        return TotpEnableResult(ok=False, error=TOTP_SETUP_REQUIRED_MESSAGE)

    try:
        secret = decrypt_totp_secret(method.secret_encrypted)
    except TotpEncryptionError:
        logger.error("TOTP enable failed: decryption configuration error")
        return TotpEnableResult(ok=False, error=TOTP_CONFIGURATION_ERROR_MESSAGE)

    verification = verify_totp_code(
        secret,
        code,
        last_used_timecode=method.last_used_timecode,
    )
    if not verification.ok or verification.matched_timecode is None:
        return TotpEnableResult(ok=False, error=TOTP_INVALID_CODE_MESSAGE)

    now = _utcnow()
    try:
        method.enabled = True
        method.verified_at = now
        method.last_used_timecode = verification.matched_timecode
        _record_event(user_id=user.id, event_type=EVENT_TOTP_ENABLED, ip_address=ip_address)
        revoke_all_sessions_for_user(user)
        raw_token, _new_session = create_session(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    _send_security_notification(
        to_address=user.email,
        subject=_ENABLE_NOTIFY_SUBJECT,
        text_body=_ENABLE_NOTIFY_BODY,
    )
    return TotpEnableResult(ok=True, raw_token=raw_token)


def disable_totp(
    user: User,
    current_session: Session,
    *,
    current_password: str,
    code: str,
    ip_address: str | None = None,
) -> TotpDisableResult:
    """Disable TOTP after password + current code reauthentication."""
    if current_session.user_id != user.id:
        raise ValueError("current_session does not belong to user")

    if not verify_password(user.password_hash, current_password):
        return TotpDisableResult(ok=False, error=CURRENT_PASSWORD_INCORRECT_MESSAGE)

    method = user.totp_method
    if method is None or not method.enabled:
        return TotpDisableResult(ok=False, error=TOTP_NOT_ENABLED_MESSAGE)

    try:
        secret = decrypt_totp_secret(method.secret_encrypted)
    except TotpEncryptionError:
        logger.error("TOTP disable failed: decryption configuration error")
        return TotpDisableResult(ok=False, error=TOTP_CONFIGURATION_ERROR_MESSAGE)

    verification = verify_totp_code(
        secret,
        code,
        last_used_timecode=method.last_used_timecode,
    )
    if not verification.ok or verification.matched_timecode is None:
        return TotpDisableResult(ok=False, error=TOTP_INVALID_CODE_MESSAGE)

    try:
        # Consume the matched timecode on the row before delete for consistency;
        # the row is then removed so the encrypted secret leaves active storage.
        method.last_used_timecode = verification.matched_timecode
        db.session.delete(method)
        _record_event(user_id=user.id, event_type=EVENT_TOTP_DISABLED, ip_address=ip_address)
        revoke_all_sessions_for_user(user)
        raw_token, _new_session = create_session(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    _send_security_notification(
        to_address=user.email,
        subject=_DISABLE_NOTIFY_SUBJECT,
        text_body=_DISABLE_NOTIFY_BODY,
    )
    return TotpDisableResult(ok=True, raw_token=raw_token)
