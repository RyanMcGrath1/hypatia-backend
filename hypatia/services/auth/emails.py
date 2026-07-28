"""Shared email normalization and format validation for auth flows."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Reasonable format check only; not a full RFC parser.
_EMAIL_FORMAT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_EMAIL_LENGTH = 255


def normalize_email(email: str) -> str:
    """Normalize email for storage and lookup (strip + casefold).

    Registration and login must both use this helper so casing/whitespace
    variants cannot create or miss separate accounts.
    """
    return email.strip().casefold()


@dataclass(frozen=True, slots=True)
class EmailValidationResult:
    ok: bool
    error: str | None = None
    normalized: str | None = None


def validate_email(email: str) -> EmailValidationResult:
    """Validate and normalize an email for registration."""
    if email == "":
        return EmailValidationResult(ok=False, error="Email is required")

    normalized = normalize_email(email)
    if not normalized:
        return EmailValidationResult(ok=False, error="Email is required")

    if len(normalized) > MAX_EMAIL_LENGTH:
        return EmailValidationResult(
            ok=False,
            error=f"Email must be at most {MAX_EMAIL_LENGTH} characters",
        )

    if _EMAIL_FORMAT_RE.fullmatch(normalized) is None:
        return EmailValidationResult(ok=False, error="Invalid email address")

    return EmailValidationResult(ok=True, normalized=normalized)
