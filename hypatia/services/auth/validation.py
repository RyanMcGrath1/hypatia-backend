"""Password validation for registration and future password-change flows."""

from __future__ import annotations

from dataclasses import dataclass

MIN_PASSWORD_LENGTH = 12


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
