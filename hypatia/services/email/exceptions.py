"""Application-level email delivery failures."""

from __future__ import annotations


class EmailError(Exception):
    """Base class for outbound email failures."""

    code = "EMAIL_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class EmailNotConfiguredError(EmailError):
    """Required SMTP / From settings are missing or incomplete."""

    code = "EMAIL_NOT_CONFIGURED"


class EmailDeliveryError(EmailError):
    """SMTP or network failure while sending (credentials never included)."""

    code = "EMAIL_DELIVERY_FAILED"
