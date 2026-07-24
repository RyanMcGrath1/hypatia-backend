"""Change-email flow with dual confirmation (current + proposed address).

SMTP delivery is never perfectly atomic with the database because SMTP is an
external system. Pending requests are committed before send; on known delivery
failure the pending row is deleted in a compensating transaction so it cannot
be used. Expired/completed rows may remain until a future cleanup job.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import current_app
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from hypatia.extensions import db
from hypatia.models import AccountEvent, EmailChangeRequest, User
from hypatia.services.account.password import CURRENT_PASSWORD_INCORRECT_MESSAGE
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_ACTIVE,
    EMAIL_ALREADY_REGISTERED_MESSAGE,
    EVENT_EMAIL_CHANGE_REQUESTED,
    EVENT_EMAIL_CHANGED,
)
from hypatia.services.auth.emails import validate_email
from hypatia.services.auth.passwords import verify_password
from hypatia.services.auth.sessions import revoke_all_sessions_for_user
from hypatia.services.email import (
    EmailDeliveryError,
    EmailNotConfiguredError,
    send_email,
)

logger = logging.getLogger(__name__)

TOKEN_RANDOM_BYTES = 32

NEW_EMAIL_SAME_AS_CURRENT_MESSAGE = "New email must be different from your current email"
INVALID_VERIFICATION_TOKEN_MESSAGE = "Invalid or expired verification token"
EMAIL_DELIVERY_FAILED_MESSAGE = "Verification email delivery failed"
EMAIL_CHANGE_CONFIRMATION_MESSAGE = "Email confirmation recorded"
EMAIL_CHANGE_COMPLETE_MESSAGE = "Email address changed successfully"
EMAIL_CHANGE_UNAVAILABLE_MESSAGE = "Email change could not be completed"
VERIFY_URL_NOT_CONFIGURED_MESSAGE = "Email change verification is not configured"

_OLD_CONFIRM_SUBJECT = "Confirm your Hypatia email change"
_NEW_CONFIRM_SUBJECT = "Confirm your email address for Hypatia"
_OLD_NOTIFY_SUBJECT = "Your Hypatia account email was changed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize DB timestamps (SQLite may return naive UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def generate_email_change_token() -> str:
    """Return a new opaque verification token (never stored in the database)."""
    return secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def hash_email_change_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest stored for ``raw_token``."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _token_ttl() -> timedelta:
    hours = int(current_app.config.get("EMAIL_CHANGE_TOKEN_TTL_HOURS", 8))
    return timedelta(hours=max(hours, 1))


def _verify_url_base() -> str:
    return str(current_app.config.get("EMAIL_CHANGE_VERIFY_URL", "") or "").strip()


def build_email_change_verify_url(base_url: str, raw_token: str) -> str:
    """Append ``token`` as a query parameter without logging the result."""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["token"] = raw_token
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _email_owned_by_other_user(normalized_email: str, *, exclude_user_id) -> bool:
    existing = db.session.scalar(
        select(User.id).where(
            func.lower(User.email) == normalized_email,
            User.id != exclude_user_id,
        )
    )
    return existing is not None


def _delete_pending_requests_for_user(user_id) -> None:
    pending = db.session.scalars(
        select(EmailChangeRequest).where(
            EmailChangeRequest.user_id == user_id,
            EmailChangeRequest.completed_at.is_(None),
        )
    ).all()
    for row in pending:
        db.session.delete(row)


def _record_event(*, user_id, event_type: str, ip_address: str | None) -> None:
    db.session.add(
        AccountEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
        )
    )


def _old_confirmation_body(*, new_email: str, verify_url: str) -> str:
    return (
        "A request was made to change the email address on your Hypatia account "
        f"from this address to {new_email}. Confirm this change using the link "
        "below. If you did not request this change, do not confirm it.\n\n"
        f"{verify_url}\n"
    )


def _new_confirmation_body(*, verify_url: str) -> str:
    return (
        "Confirm this email address for your Hypatia account.\n\n"
        f"{verify_url}\n"
    )


def _old_notification_body() -> str:
    return "The email address on your Hypatia account has been changed.\n"


@dataclass(frozen=True, slots=True)
class RequestEmailChangeResult:
    ok: bool
    error: str | None = None
    delivery_failed: bool = False
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class VerifyEmailChangeResult:
    ok: bool
    error: str | None = None
    message: str | None = None
    email_change_complete: bool = False
    conflict: bool = False


def request_email_change(
    user: User,
    *,
    new_email: str,
    current_password: str,
    ip_address: str | None = None,
) -> RequestEmailChangeResult:
    """Start dual-confirmation email change for the authenticated user.

    Does not modify ``users.email``. Persists a pending request, then sends
    confirmation mail to the current and proposed addresses. On SMTP failure,
    the pending request is deleted and no ``EMAIL_CHANGE_REQUESTED`` is created.
    """
    if not verify_password(user.password_hash, current_password):
        return RequestEmailChangeResult(
            ok=False, error=CURRENT_PASSWORD_INCORRECT_MESSAGE
        )

    email_result = validate_email(new_email)
    if not email_result.ok or email_result.normalized is None:
        return RequestEmailChangeResult(ok=False, error=email_result.error)

    normalized_new = email_result.normalized
    if normalized_new == user.email:
        return RequestEmailChangeResult(
            ok=False, error=NEW_EMAIL_SAME_AS_CURRENT_MESSAGE
        )

    if _email_owned_by_other_user(normalized_new, exclude_user_id=user.id):
        return RequestEmailChangeResult(
            ok=False,
            error=EMAIL_ALREADY_REGISTERED_MESSAGE,
            conflict=True,
        )

    verify_base = _verify_url_base()
    if not verify_base:
        return RequestEmailChangeResult(
            ok=False,
            error=VERIFY_URL_NOT_CONFIGURED_MESSAGE,
            delivery_failed=True,
        )

    old_raw = generate_email_change_token()
    new_raw = generate_email_change_token()
    # Tokens must differ; regenerating on the astronomically unlikely collision.
    while new_raw == old_raw:
        new_raw = generate_email_change_token()

    now = _utcnow()
    pending = EmailChangeRequest(
        user_id=user.id,
        old_email=user.email,
        new_email=normalized_new,
        old_email_token_hash=hash_email_change_token(old_raw),
        new_email_token_hash=hash_email_change_token(new_raw),
        created_at=now,
        expires_at=now + _token_ttl(),
    )

    try:
        _delete_pending_requests_for_user(user.id)
        db.session.add(pending)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    old_url = build_email_change_verify_url(verify_base, old_raw)
    new_url = build_email_change_verify_url(verify_base, new_raw)

    try:
        send_email(
            to_address=pending.old_email,
            subject=_OLD_CONFIRM_SUBJECT,
            text_body=_old_confirmation_body(
                new_email=pending.new_email, verify_url=old_url
            ),
        )
        send_email(
            to_address=pending.new_email,
            subject=_NEW_CONFIRM_SUBJECT,
            text_body=_new_confirmation_body(verify_url=new_url),
        )
    except (EmailDeliveryError, EmailNotConfiguredError):
        try:
            db.session.delete(pending)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return RequestEmailChangeResult(
            ok=False,
            error=EMAIL_DELIVERY_FAILED_MESSAGE,
            delivery_failed=True,
        )

    try:
        _record_event(
            user_id=user.id,
            event_type=EVENT_EMAIL_CHANGE_REQUESTED,
            ip_address=ip_address,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return RequestEmailChangeResult(ok=True)


def _request_is_usable(request: EmailChangeRequest, *, now: datetime) -> bool:
    if request.completed_at is not None:
        return False
    if _as_utc(request.expires_at) <= now:
        return False
    return True


def _complete_email_change(
    request: EmailChangeRequest,
    *,
    now: datetime,
    ip_address: str | None,
) -> VerifyEmailChangeResult | None:
    """Apply the email change when both sides are confirmed.

    Returns ``None`` when the change committed successfully. Returns an error
    result when completion cannot proceed (caller should not commit further).
    """
    user = db.session.get(User, request.user_id)
    if user is None or user.account_status != ACCOUNT_STATUS_ACTIVE:
        db.session.delete(request)
        db.session.commit()
        return VerifyEmailChangeResult(
            ok=False, error=EMAIL_CHANGE_UNAVAILABLE_MESSAGE
        )

    if user.email != request.old_email:
        db.session.delete(request)
        db.session.commit()
        return VerifyEmailChangeResult(
            ok=False, error=EMAIL_CHANGE_UNAVAILABLE_MESSAGE
        )

    if _email_owned_by_other_user(request.new_email, exclude_user_id=user.id):
        db.session.delete(request)
        db.session.commit()
        return VerifyEmailChangeResult(
            ok=False,
            error=EMAIL_ALREADY_REGISTERED_MESSAGE,
            conflict=True,
        )

    old_email = request.old_email
    user.email = request.new_email
    user.email_verified = True
    request.completed_at = now
    revoke_all_sessions_for_user(user)
    _record_event(
        user_id=user.id,
        event_type=EVENT_EMAIL_CHANGED,
        ip_address=ip_address,
    )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        stale = db.session.get(EmailChangeRequest, request.id)
        if stale is not None:
            db.session.delete(stale)
            db.session.commit()
        return VerifyEmailChangeResult(
            ok=False,
            error=EMAIL_ALREADY_REGISTERED_MESSAGE,
            conflict=True,
        )

    try:
        send_email(
            to_address=old_email,
            subject=_OLD_NOTIFY_SUBJECT,
            text_body=_old_notification_body(),
        )
    except (EmailDeliveryError, EmailNotConfiguredError) as exc:
        logger.error(
            "Post-change old-email notification failed user_id=%s error_type=%s",
            user.id,
            type(exc).__name__,
        )

    return None


def verify_email_change(
    *,
    raw_token: str,
    ip_address: str | None = None,
) -> VerifyEmailChangeResult:
    """Confirm one side of a pending email change, or complete when both done.

    Ownership is established by the emailed opaque token; no session is required.
    Does not issue a replacement session after completion — the user must log in
    again with the new email.
    """
    if not isinstance(raw_token, str) or not raw_token:
        return VerifyEmailChangeResult(
            ok=False, error=INVALID_VERIFICATION_TOKEN_MESSAGE
        )

    token_hash = hash_email_change_token(raw_token)
    request = db.session.scalar(
        select(EmailChangeRequest).where(
            or_(
                EmailChangeRequest.old_email_token_hash == token_hash,
                EmailChangeRequest.new_email_token_hash == token_hash,
            )
        )
    )
    now = _utcnow()
    if request is None or not _request_is_usable(request, now=now):
        return VerifyEmailChangeResult(
            ok=False, error=INVALID_VERIFICATION_TOKEN_MESSAGE
        )

    is_old = request.old_email_token_hash == token_hash
    is_new = request.new_email_token_hash == token_hash
    if not is_old and not is_new:
        return VerifyEmailChangeResult(
            ok=False, error=INVALID_VERIFICATION_TOKEN_MESSAGE
        )

    already_confirmed = (
        (is_old and request.old_email_confirmed_at is not None)
        or (is_new and request.new_email_confirmed_at is not None)
    )

    if not already_confirmed:
        if is_old:
            request.old_email_confirmed_at = now
        else:
            request.new_email_confirmed_at = now

    both_confirmed = (
        request.old_email_confirmed_at is not None
        and request.new_email_confirmed_at is not None
    )

    if both_confirmed:
        # Re-check expiry immediately before mutating users.email.
        if _as_utc(request.expires_at) <= now:
            return VerifyEmailChangeResult(
                ok=False, error=INVALID_VERIFICATION_TOKEN_MESSAGE
            )
        completion_error = _complete_email_change(
            request, now=now, ip_address=ip_address
        )
        if completion_error is not None:
            return completion_error
        return VerifyEmailChangeResult(
            ok=True,
            message=EMAIL_CHANGE_COMPLETE_MESSAGE,
            email_change_complete=True,
        )

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return VerifyEmailChangeResult(
        ok=True,
        message=EMAIL_CHANGE_CONFIRMATION_MESSAGE,
        email_change_complete=False,
    )
