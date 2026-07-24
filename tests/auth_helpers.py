"""Shared helpers for authentication tests."""

from __future__ import annotations

import json
from datetime import datetime

from hypatia.models import Profile, User
from hypatia.services.auth.emails import normalize_email
from hypatia.services.auth.passwords import hash_password


def create_user(
    session,
    *,
    email: str,
    password: str,
    account_status: str = "active",
    first_name: str | None = None,
    last_name: str | None = None,
    password_changed_at: datetime | None = None,
) -> User:
    """Create a User, optionally with a matching Profile.

    Registration always creates a Profile. Pass ``first_name`` and ``last_name``
    together when tests need a consistent User + Profile account. Omitting both
    keeps the User-only helper used by older auth tests.
    """
    if (first_name is None) ^ (last_name is None):
        raise ValueError("first_name and last_name must both be provided or both omitted")

    user = User(
        email=normalize_email(email),
        password_hash=hash_password(password),
        account_status=account_status,
        password_changed_at=password_changed_at,
    )
    session.add(user)
    session.flush()

    if first_name is not None and last_name is not None:
        session.add(
            Profile(
                user_id=user.id,
                first_name=first_name,
                last_name=last_name,
            )
        )

    session.commit()
    return user


def create_user_with_profile(
    session,
    *,
    email: str,
    password: str,
    first_name: str = "Matthew",
    last_name: str = "Thompson",
    account_status: str = "active",
    password_changed_at: datetime | None = None,
) -> User:
    """Create a valid User + Profile account for Profile API tests."""
    return create_user(
        session,
        email=email,
        password=password,
        account_status=account_status,
        first_name=first_name,
        last_name=last_name,
        password_changed_at=password_changed_at,
    )


def login(client, *, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": email, "password": password}),
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    return payload["token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
