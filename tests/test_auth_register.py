"""Registration route tests."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from hypatia.models import AccountEvent, Profile, Session, User
from hypatia.services.auth.constants import (
    EMAIL_ALREADY_REGISTERED_MESSAGE,
    EVENT_ACCOUNT_CREATED,
)
from hypatia.services.auth.sessions import hash_session_token, validate_session


def _register_payload(**overrides):
    payload = {
        "email": "user@example.com",
        "password": "validpassword12",
        "first_name": "Matthew",
        "last_name": "Thompson",
    }
    payload.update(overrides)
    return payload


def test_valid_register_returns_201_and_token(client, db_session) -> None:
    response = client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload()),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["message"] == "Registration successful"
    assert payload["token"]
    assert "password" not in payload
    assert "password_hash" not in payload
    assert "token_hash" not in payload


def test_returned_token_authenticates_through_session_validation(client, db_session) -> None:
    response = client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload()),
        content_type="application/json",
    )
    raw_token = response.get_json()["token"]

    result = validate_session(raw_token)
    assert result.valid is True

    session = db_session.scalar(select(Session))
    assert session is not None
    assert session.token_hash == hash_session_token(raw_token)
    assert session.token_hash != raw_token


def test_malformed_json_rejected(client) -> None:
    response = client.post(
        "/api/auth/register",
        data="not json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_missing_fields_rejected(client, db_session) -> None:
    response = client.post(
        "/api/auth/register",
        data=json.dumps({"email": "user@example.com"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "password is required"


def test_duplicate_email_conflict(client, db_session) -> None:
    client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload()),
        content_type="application/json",
    )
    response = client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload(email="  USER@example.com ")),
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": EMAIL_ALREADY_REGISTERED_MESSAGE}
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(select(func.count()).select_from(Profile)) == 1


def test_invalid_password_rejected(client, db_session) -> None:
    response = client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload(password="short")),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "15" in response.get_json()["error"]
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_register_creates_account_created_event(client, db_session) -> None:
    client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload()),
        content_type="application/json",
    )

    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_ACCOUNT_CREATED
        )
    ) == 1


def test_failed_register_does_not_create_account_created_event(client, db_session) -> None:
    client.post(
        "/api/auth/register",
        data=json.dumps(_register_payload(password="short")),
        content_type="application/json",
    )

    assert db_session.scalar(select(func.count()).select_from(AccountEvent)) == 0
