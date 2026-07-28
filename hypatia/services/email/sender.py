"""Reusable SMTP email delivery for transactional account-security mail.

Callers should use ``send_email`` only — never open SMTP from routes or
account services. Plain text only for now (no HTML templates).
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from flask import current_app, has_app_context

from hypatia.services.email.exceptions import (
    EmailDeliveryError,
    EmailNotConfiguredError,
)

logger = logging.getLogger(__name__)

SMTP_SECURITY_STARTTLS = "starttls"
SMTP_SECURITY_SSL = "ssl"
SMTP_SECURITY_NONE = "none"
SMTP_SECURITY_MODES = frozenset(
    {SMTP_SECURITY_STARTTLS, SMTP_SECURITY_SSL, SMTP_SECURITY_NONE}
)

_DEFAULT_PORTS = {
    SMTP_SECURITY_STARTTLS: 587,
    SMTP_SECURITY_SSL: 465,
    SMTP_SECURITY_NONE: 25,
}

_DEFAULT_TIMEOUT_S = 30.0


@dataclass(frozen=True, slots=True)
class EmailSettings:
    """Validated SMTP + From settings used by ``send_email``."""

    smtp_host: str
    smtp_port: int
    smtp_security: str
    from_address: str
    from_name: str
    smtp_username: str = ""
    smtp_password: str = ""
    timeout_s: float = _DEFAULT_TIMEOUT_S

    @property
    def has_credentials(self) -> bool:
        return bool(self.smtp_username) and bool(self.smtp_password)


def _config_get(
    source: Mapping[str, Any] | None,
    key: str,
    *,
    allow_environ: bool,
) -> str | None:
    """Return a stripped string from ``source`` and optionally ``os.environ``."""
    if source is not None and key in source:
        raw = source.get(key)
        if raw is not None:
            text = str(raw).strip()
            if text:
                return text
        if not allow_environ:
            return None
        # Empty app.config value: fall through to process env (post-dotenv).
    elif source is not None and not allow_environ:
        return None

    if not allow_environ:
        return None

    env_raw = os.environ.get(key)
    if env_raw is None:
        return None
    text = env_raw.strip()
    return text if text else None


def _parse_port(raw: str | None, *, security: str) -> int:
    if raw is None:
        return _DEFAULT_PORTS[security]
    try:
        port = int(raw)
    except ValueError as exc:
        raise EmailNotConfiguredError(
            f"SMTP_PORT must be an integer, got {raw!r}"
        ) from exc
    if not (1 <= port <= 65535):
        raise EmailNotConfiguredError(
            f"SMTP_PORT must be between 1 and 65535, got {port}"
        )
    return port


def _parse_timeout(raw: str | None, source: Mapping[str, Any] | None) -> float:
    if raw is not None:
        try:
            timeout = float(raw)
        except ValueError as exc:
            raise EmailNotConfiguredError(
                f"SMTP_TIMEOUT_S must be a number, got {raw!r}"
            ) from exc
        if timeout <= 0:
            raise EmailNotConfiguredError("SMTP_TIMEOUT_S must be positive")
        return timeout
    if source is not None:
        cfg_timeout = source.get("SMTP_TIMEOUT_S")
        if cfg_timeout is not None and str(cfg_timeout).strip() != "":
            try:
                timeout = float(cfg_timeout)
            except (TypeError, ValueError) as exc:
                raise EmailNotConfiguredError(
                    f"SMTP_TIMEOUT_S must be a number, got {cfg_timeout!r}"
                ) from exc
            if timeout <= 0:
                raise EmailNotConfiguredError("SMTP_TIMEOUT_S must be positive")
            return timeout
    return _DEFAULT_TIMEOUT_S


def load_email_settings(source: Mapping[str, Any] | None = None) -> EmailSettings:
    """Load and validate email settings from app config / environment.

    When ``source`` is provided (typical in tests), only that mapping is used.
    Otherwise values come from ``current_app.config`` with ``os.environ``
    fallback so `.env` loaded at app startup is visible.

    Raises:
        EmailNotConfiguredError: required values missing or incomplete.
        ValueError: ``SMTP_SECURITY`` is set to an unsupported mode.
    """
    if source is not None:
        cfg: Mapping[str, Any] | None = source
        allow_environ = False
    elif has_app_context():
        cfg = current_app.config
        allow_environ = True
    else:
        cfg = None
        allow_environ = True

    security_raw = _config_get(cfg, "SMTP_SECURITY", allow_environ=allow_environ)
    security = (security_raw or SMTP_SECURITY_STARTTLS).casefold()
    if security not in SMTP_SECURITY_MODES:
        raise ValueError(
            "SMTP_SECURITY must be one of: "
            f"{', '.join(sorted(SMTP_SECURITY_MODES))} "
            f"(got {security_raw!r})"
        )

    host = _config_get(cfg, "SMTP_HOST", allow_environ=allow_environ)
    from_address = _config_get(cfg, "EMAIL_FROM_ADDRESS", allow_environ=allow_environ)
    from_name = _config_get(cfg, "EMAIL_FROM_NAME", allow_environ=allow_environ) or ""
    username = _config_get(cfg, "SMTP_USERNAME", allow_environ=allow_environ) or ""
    password = _config_get(cfg, "SMTP_PASSWORD", allow_environ=allow_environ) or ""
    port_raw = _config_get(cfg, "SMTP_PORT", allow_environ=allow_environ)
    timeout_raw = _config_get(cfg, "SMTP_TIMEOUT_S", allow_environ=allow_environ)

    missing: list[str] = []
    if not host:
        missing.append("SMTP_HOST")
    if not from_address:
        missing.append("EMAIL_FROM_ADDRESS")
    if missing:
        raise EmailNotConfiguredError(
            "Email delivery is not configured; missing: " + ", ".join(missing)
        )

    if bool(username) != bool(password):
        raise EmailNotConfiguredError(
            "Email delivery is not configured; SMTP_USERNAME and SMTP_PASSWORD "
            "must both be set or both be empty"
        )

    port = _parse_port(port_raw, security=security)
    timeout_s = _parse_timeout(timeout_raw, cfg)

    if security == SMTP_SECURITY_NONE:
        logger.warning(
            "SMTP_SECURITY=none is configured; use only for a trusted local or "
            "relay path. Prefer starttls or ssl in production."
        )

    return EmailSettings(
        smtp_host=host,
        smtp_port=port,
        smtp_security=security,
        from_address=from_address,
        from_name=from_name,
        smtp_username=username,
        smtp_password=password,
        timeout_s=timeout_s,
    )


def build_message(
    *,
    to_address: str,
    subject: str,
    text_body: str,
    from_address: str,
    from_name: str = "",
) -> EmailMessage:
    """Build a standards-compliant plain-text email message."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = to_address
    msg.set_content(text_body)
    return msg


def _recipient_domain(address: str) -> str:
    _, _, domain = address.rpartition("@")
    return domain.casefold() if domain else "(unknown)"


def _open_smtp(settings: EmailSettings):
    """Create an SMTP client for the configured security mode (caller must close)."""
    host = settings.smtp_host
    port = settings.smtp_port
    timeout = settings.timeout_s

    if settings.smtp_security == SMTP_SECURITY_SSL:
        return smtplib.SMTP_SSL(host, port, timeout=timeout)

    client = smtplib.SMTP(host, port, timeout=timeout)
    try:
        if settings.smtp_security == SMTP_SECURITY_STARTTLS:
            client.starttls()
    except Exception:
        try:
            client.close()
        except Exception:
            pass
        raise
    return client


def send_email(
    *,
    to_address: str,
    subject: str,
    text_body: str,
    settings: EmailSettings | None = None,
) -> None:
    """Send a plain-text transactional email via SMTP.

    Raises:
        EmailNotConfiguredError: SMTP / From settings are incomplete.
        ValueError: invalid ``SMTP_SECURITY`` when loading settings.
        EmailDeliveryError: SMTP or network failure (no credentials in message).
    """
    resolved = settings if settings is not None else load_email_settings()
    message = build_message(
        to_address=to_address,
        subject=subject,
        text_body=text_body,
        from_address=resolved.from_address,
        from_name=resolved.from_name,
    )

    domain = _recipient_domain(to_address)
    started = time.perf_counter()
    logger.info(
        "Email delivery attempted host=%s security=%s recipient_domain=%s",
        resolved.smtp_host,
        resolved.smtp_security,
        domain,
    )

    client = None
    try:
        client = _open_smtp(resolved)
        if resolved.has_credentials:
            client.login(resolved.smtp_username, resolved.smtp_password)
        client.send_message(message)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.error(
            "Email delivery failed host=%s recipient_domain=%s "
            "duration_ms=%s error_type=%s",
            resolved.smtp_host,
            domain,
            duration_ms,
            type(exc).__name__,
        )
        raise EmailDeliveryError(
            f"Email delivery failed ({type(exc).__name__})"
        ) from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    logger.debug(
                        "SMTP connection cleanup failed host=%s",
                        resolved.smtp_host,
                    )

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Email delivery succeeded host=%s recipient_domain=%s duration_ms=%s",
        resolved.smtp_host,
        domain,
        duration_ms,
    )
