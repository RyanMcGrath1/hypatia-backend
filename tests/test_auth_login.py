"""Login route tests."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from hypatia.models import AccountEvent, MfaLoginChallenge, Profile, Session, User
from hypatia.services.auth.constants import EVENT_LOGIN_SUCCESS, INVALID_CREDENTIALS_MESSAGE
from hypatia.services.auth.passwords import _DUMMY_PASSWORD_PLAINTEXT
from hypatia.services.auth.sessions import hash_session_token
from tests.auth_helpers import create_user


def test_missing_json_body_rejected(client) -> None:
    response = client.post("/api/auth/login", data="not json", content_type="application/json")

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_missing_email_field_rejected(client, db_session) -> None:
    response = client.post(
        "/api/auth/login",
        data=json.dumps({"password": "validpassword12"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "email is required"


def test_missing_password_field_rejected(client, db_session) -> None:
    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "password is required"


def test_invalid_credentials_return_intended_error(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "wrongpassword12"}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}


def test_valid_credentials_return_session_token(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "validpassword12"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Login successful"
    assert payload["token"]
    assert "password" not in payload
    assert "password_hash" not in payload


def test_successful_login_creates_session_row(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "validpassword12"}),
        content_type="application/json",
    )

    assert db_session.scalar(select(func.count()).select_from(Session)) == 1


def test_successful_login_does_not_store_raw_token(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "validpassword12"}),
        content_type="application/json",
    )
    raw_token = response.get_json()["token"]
    session = db_session.scalar(select(Session))

    assert session is not None
    assert session.token_hash == hash_session_token(raw_token)
    assert session.token_hash != raw_token


def test_returned_token_authenticates(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "validpassword12"}),
        content_type="application/json",
    )
    raw_token = response.get_json()["token"]

    from hypatia.services.auth.sessions import validate_session

    result = validate_session(raw_token)
    assert result.valid is True


def test_invalid_login_does_not_create_session(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "wrongpassword12"}),
        content_type="application/json",
    )

    assert db_session.scalar(select(func.count()).select_from(Session)) == 0


def test_unknown_and_wrong_password_login_responses_are_equivalent(client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    wrong_password = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": "wrongpassword12"}),
        content_type="application/json",
    )
    unknown_email = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "missing@example.com", "password": "validpassword12"}),
        content_type="application/json",
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.get_json() == unknown_email.get_json() == {
        "error": INVALID_CREDENTIALS_MESSAGE
    }


def test_unknown_email_with_dummy_plaintext_still_fails_http(client, db_session) -> None:
    users_before = db_session.scalar(select(func.count()).select_from(User)) or 0
    profiles_before = db_session.scalar(select(func.count()).select_from(Profile)) or 0

    response = client.post(
        "/api/auth/login",
        data=json.dumps(
            {
                "email": "missing@example.com",
                "password": _DUMMY_PASSWORD_PLAINTEXT,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0
    assert db_session.scalar(select(func.count()).select_from(MfaLoginChallenge)) == 0
    assert db_session.scalar(select(func.count()).select_from(User)) == users_before
    assert db_session.scalar(select(func.count()).select_from(Profile)) == profiles_before
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AccountEvent)
            .where(AccountEvent.event_type == EVENT_LOGIN_SUCCESS)
        )
        == 0
    )


def test_unknown_email_login_http_has_no_auth_side_effects(client, db_session) -> None:
    users_before = db_session.scalar(select(func.count()).select_from(User)) or 0
    profiles_before = db_session.scalar(select(func.count()).select_from(Profile)) or 0

    response = client.post(
        "/api/auth/login",
        data=json.dumps(
            {
                "email": "nobody@example.com",
                "password": "validpassword12",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}
    assert "challenge_token" not in response.get_json()
    assert "token" not in response.get_json()
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0
    assert db_session.scalar(select(func.count()).select_from(MfaLoginChallenge)) == 0
    assert db_session.scalar(select(func.count()).select_from(User)) == users_before
    assert db_session.scalar(select(func.count()).select_from(Profile)) == profiles_before
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AccountEvent)
            .where(AccountEvent.event_type == EVENT_LOGIN_SUCCESS)
        )
        == 0
    )
