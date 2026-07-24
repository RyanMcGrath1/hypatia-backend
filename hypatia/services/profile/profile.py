"""Current-user Profile retrieval and name updates."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from hypatia.models import Profile, User
from hypatia.services.auth.registration import MAX_NAME_LENGTH
from hypatia.services.security.totp import user_has_totp_enabled

logger = logging.getLogger(__name__)

ALLOWED_PATCH_FIELDS = frozenset({"first_name", "last_name"})
PROFILE_UNAVAILABLE_MESSAGE = "Profile unavailable"
NO_UPDATABLE_FIELDS_MESSAGE = "No updatable fields provided"


@dataclass(frozen=True, slots=True)
class ProfileView:
    first_name: str
    last_name: str
    date_joined: str
    email: str
    password_changed_at: str | None
    totp_enabled: bool

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_joined": self.date_joined,
            "email": self.email,
            "password_changed_at": self.password_changed_at,
            "totp_enabled": self.totp_enabled,
        }


@dataclass(frozen=True, slots=True)
class ProfileResult:
    ok: bool
    error: str | None = None
    missing_profile: bool = False
    profile: ProfileView | None = None


def _as_utc(value: datetime) -> datetime:
    """Normalize DB timestamps (SQLite may return naive UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso8601(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).replace(microsecond=0).isoformat()


def _validate_name(value: object, field_name: str) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, f"{field_name} must be a string"

    trimmed = value.strip()
    if not trimmed:
        return None, f"{field_name} is required"
    if len(trimmed) > MAX_NAME_LENGTH:
        return None, f"{field_name} must be at most {MAX_NAME_LENGTH} characters"
    return trimmed, None


def _build_view(user: User, profile: Profile) -> ProfileView:
    return ProfileView(
        first_name=profile.first_name,
        last_name=profile.last_name,
        date_joined=_iso8601(user.created_at) or "",
        email=user.email,
        password_changed_at=_iso8601(user.password_changed_at),
        totp_enabled=user_has_totp_enabled(user),
    )


def _missing_profile_result(user: User) -> ProfileResult:
    # Registration always creates a Profile. A missing row is an inconsistent account
    # state — do not auto-create; return a clean 500-class API error and log for ops.
    logger.error(
        "Authenticated user %s is missing a Profile row",
        user.id,
    )
    return ProfileResult(
        ok=False,
        error=PROFILE_UNAVAILABLE_MESSAGE,
        missing_profile=True,
    )


def get_profile(user: User) -> ProfileResult:
    """Return the authenticated user's Profile page representation."""
    profile = user.profile
    if profile is None:
        return _missing_profile_result(user)
    return ProfileResult(ok=True, profile=_build_view(user, profile))


def update_profile(user: User, data: Any) -> ProfileResult:
    """Update first_name and/or last_name for the authenticated user.

    Unknown JSON fields are rejected so protected attributes (email, user_id, etc.)
    cannot silently appear successful. Identity always comes from ``user``, never
    from request parameters.

    No ``PROFILE_UPDATED`` AccountEvent is recorded: name edits are not
    security/account-sensitive events for the current audit table.
    """
    if not isinstance(data, dict):
        return ProfileResult(ok=False, error=NO_UPDATABLE_FIELDS_MESSAGE)

    unknown = sorted(set(data) - ALLOWED_PATCH_FIELDS)
    if unknown:
        return ProfileResult(ok=False, error=f"Unknown field: {unknown[0]}")

    if not data:
        return ProfileResult(ok=False, error=NO_UPDATABLE_FIELDS_MESSAGE)

    if "first_name" not in data and "last_name" not in data:
        return ProfileResult(ok=False, error=NO_UPDATABLE_FIELDS_MESSAGE)

    updates: dict[str, str] = {}
    if "first_name" in data:
        trimmed, error = _validate_name(data["first_name"], "first_name")
        if error is not None or trimmed is None:
            return ProfileResult(ok=False, error=error)
        updates["first_name"] = trimmed

    if "last_name" in data:
        trimmed, error = _validate_name(data["last_name"], "last_name")
        if error is not None or trimmed is None:
            return ProfileResult(ok=False, error=error)
        updates["last_name"] = trimmed

    profile = user.profile
    if profile is None:
        return _missing_profile_result(user)

    # Unchanged values: skip attribute writes so Profile.updated_at is not churned.
    # Caller (@auth_required) still commits once for session bookkeeping.
    if "first_name" in updates and updates["first_name"] != profile.first_name:
        profile.first_name = updates["first_name"]
    if "last_name" in updates and updates["last_name"] != profile.last_name:
        profile.last_name = updates["last_name"]

    return ProfileResult(ok=True, profile=_build_view(user, profile))