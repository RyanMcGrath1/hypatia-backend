"""Outbound transactional email delivery (SMTP)."""

from hypatia.services.email.exceptions import (
    EmailDeliveryError,
    EmailError,
    EmailNotConfiguredError,
)
from hypatia.services.email.sender import (
    SMTP_SECURITY_MODES,
    SMTP_SECURITY_NONE,
    SMTP_SECURITY_SSL,
    SMTP_SECURITY_STARTTLS,
    EmailSettings,
    build_message,
    load_email_settings,
    send_email,
)

__all__ = [
    "EmailDeliveryError",
    "EmailError",
    "EmailNotConfiguredError",
    "EmailSettings",
    "SMTP_SECURITY_MODES",
    "SMTP_SECURITY_NONE",
    "SMTP_SECURITY_SSL",
    "SMTP_SECURITY_STARTTLS",
    "build_message",
    "load_email_settings",
    "send_email",
]
