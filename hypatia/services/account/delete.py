"""Irreversible account deletion via soft-delete / anonymization.

Physically retaining the User row as a tombstone while scrubbing credentials,
personal data, and security state. Notification email is sent only after a
successful commit; delivery failure does not undo deletion.

AccountEvent rows (including ACCOUNT_DELETED) are retained with the tombstone.
Soft deletion must not remove audit history. If scheduled physical deletion of
User tombstones is implemented later, audit-log retention and the
``account_events.user_id`` FK ``ON DELETE CASCADE`` behavior must be revisited
before hard deletes are enabled.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from hypatia.extensions import db
from hypatia.models import (
    EmailChangeRequest,
    Profile,
    Session,
    User,
)
from hypatia.services.audit import record_account_event
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_DELETED,
    EVENT_ACCOUNT_DELETED,
)
from hypatia.services.auth.mfa_challenge import delete_mfa_login_challenges_for_user
from hypatia.services.auth.passwords import hash_password, verify_password
from hypatia.services.auth.sessions import revoke_all_sessions_for_user
from hypatia.services.email import EmailDeliveryError, EmailNotConfiguredError, send_email
from hypatia.services.security.totp import (
    CURRENT_PASSWORD_INCORRECT_MESSAGE,
    TOTP_CONFIGURATION_ERROR_MESSAGE,
    TOTP_INVALID_CODE_MESSAGE,
    user_has_totp_enabled,
)
from hypatia.services.security.totp_crypto import TotpEncryptionError, decrypt_totp_secret
from hypatia.services.security.totp_verify import verify_totp_code

logger = logging.getLogger(__name__)

CONFIRMATION_REQUIRED_MESSAGE = "confirmation is required"
CONFIRMATION_INVALID_MESSAGE = "confirmation must be DELETE"
TOTP_CODE_REQUIRED_MESSAGE = "totp_code is required"
TOTP_CODE_NOT_APPLICABLE_MESSAGE = "totp_code is not applicable"
ACCOUNT_DELETED_MESSAGE = "Your account has been deleted"

_DELETE_NOTIFY_SUBJECT = "Your Hypatia account has been deleted"
_DELETE_NOTIFY_BODY = "Your Hypatia account has been deleted."

DELETE_CONFIRMATION_TEXT = "DELETE"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def anonymized_deleted_email(user_id) -> str:
    """Return a non-deliverable placeholder email unique to ``user_id``."""
    return f"deleted+{user_id}@deleted.invalid"


@dataclass(frozen=True, slots=True)
class DeleteAccountResult:
    ok: bool
    error: str | None = None


def _delete_email_change_requests(user_id) -> None:
    rows = db.session.scalars(
        select(EmailChangeRequest).where(EmailChangeRequest.user_id == user_id)
    ).all()
    for row in rows:
        db.session.delete(row)


def _send_deletion_notification(*, to_address: str) -> None:
    try:
        send_email(
            to_address=to_address,
            subject=_DELETE_NOTIFY_SUBJECT,
            text_body=_DELETE_NOTIFY_BODY,
        )
    except (EmailDeliveryError, EmailNotConfiguredError) as exc:
        logger.error(
            "Account deletion notification failed error_type=%s",
            type(exc).__name__,
        )


def delete_account(
    user: User,
    current_session: Session,
    *,
    current_password: str,
    confirmation: str,
    totp_code: str | None = None,
    totp_code_provided: bool = False,
    ip_address: str | None = None,
    request_id: str | None = None,
    user_agent: str | None = None,
) -> DeleteAccountResult:
    """Soft-delete and anonymize ``user`` after password (and TOTP) reauth.

    Identity comes from ``user`` / ``current_session`` only. On success the
    User row is retained as a tombstone; Profile and security rows are removed;
    all sessions are revoked; and ``ACCOUNT_DELETED`` is recorded — all in one
    transaction. Prior ``AccountEvent`` rows remain attached to the tombstone.
    The original email is notified after commit.
    """
    if current_session.user_id != user.id:
        raise ValueError("current_session does not belong to user")

    if confirmation != DELETE_CONFIRMATION_TEXT:
        return DeleteAccountResult(ok=False, error=CONFIRMATION_INVALID_MESSAGE)

    if not verify_password(user.password_hash, current_password):
        return DeleteAccountResult(ok=False, error=CURRENT_PASSWORD_INCORRECT_MESSAGE)

    totp_enabled = user_has_totp_enabled(user)
    if totp_enabled:
        if not totp_code_provided or totp_code is None:
            return DeleteAccountResult(ok=False, error=TOTP_CODE_REQUIRED_MESSAGE)
        if not isinstance(totp_code, str):
            return DeleteAccountResult(ok=False, error=TOTP_INVALID_CODE_MESSAGE)

        method = user.totp_method
        assert method is not None
        try:
            secret = decrypt_totp_secret(method.secret_encrypted)
        except TotpEncryptionError:
            logger.error("Account deletion TOTP verify failed: decryption error")
            return DeleteAccountResult(ok=False, error=TOTP_CONFIGURATION_ERROR_MESSAGE)

        verification = verify_totp_code(
            secret,
            totp_code,
            last_used_timecode=method.last_used_timecode,
        )
        if not verification.ok or verification.matched_timecode is None:
            return DeleteAccountResult(ok=False, error=TOTP_INVALID_CODE_MESSAGE)

        # Consume the matched timecode before the method row is deleted so a
        # concurrent replay cannot reuse the same OTP against this enrollment.
        method.last_used_timecode = verification.matched_timecode
    elif totp_code_provided:
        return DeleteAccountResult(ok=False, error=TOTP_CODE_NOT_APPLICABLE_MESSAGE)

    original_email = user.email
    now = _utcnow()
    replacement_secret = secrets.token_urlsafe(64)

    try:
        user.account_status = ACCOUNT_STATUS_DELETED
        user.deleted_at = now
        user.email_verified = False
        user.email = anonymized_deleted_email(user.id)
        user.password_hash = hash_password(replacement_secret)

        profile = db.session.get(Profile, user.id)
        if profile is not None:
            db.session.delete(profile)

        method = user.totp_method
        if method is not None:
            db.session.delete(method)

        delete_mfa_login_challenges_for_user(user.id)
        _delete_email_change_requests(user.id)
        revoke_all_sessions_for_user(user)
        record_account_event(
            user,
            EVENT_ACCOUNT_DELETED,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    _send_deletion_notification(to_address=original_email)
    return DeleteAccountResult(ok=True)
