"""Shared helpers for authentication tests."""

from __future__ import annotations

import json

from hypatia.models import User
from hypatia.services.auth.passwords import hash_password


def create_user(
    session,
    *,
    email: str,
    password: str,
    account_status: str = "active",
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        account_status=account_status,
    )
    session.add(user)
    session.commit()
    return user


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
