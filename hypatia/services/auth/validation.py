"""Password validation for registration and password-change flows.

Minimum length follows NIST SP 800-63B guidance for accounts without MFA
(15 characters). No composition rules; spaces allowed; passwords are never
trimmed or normalized.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_PASSWORD_LENGTH = 15


@dataclass(frozen=True, slots=True)
class PasswordValidationResult:
    ok: bool
    error: str | None = None


def validate_password(password: str) -> PasswordValidationResult:
    """Validate a new password without modifying or normalizing it."""
    if password == "":
        return PasswordValidationResult(ok=False, error="Password is required")

    if len(password) < MIN_PASSWORD_LENGTH:
        return PasswordValidationResult(
            ok=False,
            error=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )

    return PasswordValidationResult(ok=True)
