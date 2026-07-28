"""Central account-event audit helper and request-context capture.

``record_account_event`` adds an ``AccountEvent`` to the current SQLAlchemy
session but does **not** commit. The calling business operation owns the
transaction so password change + session rotation + audit row succeed or roll
back together.

Never pass credentials, tokens, MFA secrets/codes, or verification URLs into
these helpers. Only explicitly selected safe fields are stored or logged.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from flask import g, has_request_context, request

from hypatia.extensions import db
from hypatia.models import AccountEvent, User
from hypatia.models.account_event import REQUEST_ID_MAX_LENGTH, USER_AGENT_MAX_LENGTH

SECURITY_LOGGER_NAME = "hypatia.security"

_security_logger = logging.getLogger(SECURITY_LOGGER_NAME)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AuditRequestContext:
    """Safe request metadata for account/security audit records."""

    ip_address: str | None = None
    request_id: str | None = None
    user_agent: str | None = None

    def as_kwargs(self) -> dict[str, str | None]:
        return {
            "ip_address": self.ip_address,
            "request_id": self.request_id,
            "user_agent": self.user_agent,
        }


def _bound_optional(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    if value == "":
        return None
    if len(value) <= max_length:
        return value
    return value[:max_length]


def get_audit_request_context() -> AuditRequestContext:
    """Capture IP, request id, and User-Agent from the current Flask request.

    Uses Flask's trusted ``request.remote_addr`` (do not prefer untrusted
    ``X-Forwarded-For`` here). Returns empty fields outside a request context.
    """
    if not has_request_context():
        return AuditRequestContext()

    raw_request_id = getattr(g, "request_id", None)
    request_id = raw_request_id if isinstance(raw_request_id, str) and raw_request_id else None
    user_agent = request.headers.get("User-Agent")
    if user_agent is not None and user_agent == "":
        user_agent = None

    return AuditRequestContext(
        ip_address=request.remote_addr,
        request_id=request_id,
        user_agent=user_agent,
    )


def record_account_event(
    user: User | uuid.UUID,
    event_type: str,
    *,
    ip_address: str | None = None,
    request_id: str | None = None,
    user_agent: str | None = None,
) -> AccountEvent:
    """Create an ``AccountEvent`` on the current session (does not commit)."""
    user_id = user.id if isinstance(user, User) else user
    event = AccountEvent(
        user_id=user_id,
        event_type=event_type,
        ip_address=_bound_optional(ip_address, 45),
        request_id=_bound_optional(request_id, REQUEST_ID_MAX_LENGTH),
        user_agent=_bound_optional(user_agent, USER_AGENT_MAX_LENGTH),
        created_at=_utcnow(),
    )
    db.session.add(event)
    return event


def log_security_event(
    event_type: str,
    *,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    """Emit a structured security log via the existing logging infrastructure.

    Use for security-relevant events that cannot attach to ``account_events``
    (for example ``LOGIN_FAILED`` when no User row exists). Never include
    emails, passwords, tokens, or other secrets in ``event_type`` or extras.
    """
    rid = request_id
    if rid is None and has_request_context():
        raw = getattr(g, "request_id", None)
        rid = raw if isinstance(raw, str) and raw else None

    extra: dict[str, Any] = {
        "event": "security_event",
        "event_type": event_type,
        "request_id": rid,
        "ip_address": ip_address,
    }
    if user_id is not None:
        extra["user_id"] = str(user_id)

    _security_logger.info(
        "security_event event_type=%s",
        event_type,
        extra=extra,
    )
