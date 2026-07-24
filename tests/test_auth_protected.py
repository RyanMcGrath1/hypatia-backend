"""Protected-route and logout HTTP tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from flask import g, jsonify

from hypatia.models import Session
from hypatia.services.auth.constants import UNAUTHENTICATED_MESSAGE
from hypatia.services.auth.sessions import create_session
from hypatia.utils.auth import auth_required
from sqlalchemy import func, select

from tests.auth_helpers import auth_headers, create_user, login


@pytest.fixture
def protected_client(app, db_session):
    @app.get("/api/test/protected")
    @auth_required
    def protected_route():
        return jsonify(
            {
                "user_id": str(g.current_user.id),
                "session_id": str(g.current_session.id),
            }
        )

    return app.test_client()


def test_protected_route_without_header_returns_401(protected_client) -> None:
    response = protected_client.get("/api/test/protected")
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_protected_route_with_malformed_header_returns_401(protected_client) -> None:
    response = protected_client.get(
        "/api/test/protected",
        headers={"Authorization": "Bearer"},
    )
    assert response.status_code == 401


def test_protected_route_with_wrong_scheme_returns_401(protected_client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")
    token = login(protected_client, email="user@example.com", password="validpassword12")

    response = protected_client.get(
        "/api/test/protected",
        headers={"Authorization": f"Token {token}"},
    )
    assert response.status_code == 401


def test_protected_route_with_invalid_token_returns_401(protected_client) -> None:
    response = protected_client.get(
        "/api/test/protected",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


def test_protected_route_with_valid_token_succeeds(protected_client, db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    token = login(protected_client, email="user@example.com", password="validpassword12")

    response = protected_client.get("/api/test/protected", headers=auth_headers(token))

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user_id"] == str(user.id)


def test_logout_revokes_current_session(protected_client, db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")
    token = login(protected_client, email="user@example.com", password="validpassword12")

    logout_response = protected_client.post("/api/auth/logout", headers=auth_headers(token))
    assert logout_response.status_code == 200

    session = db_session.scalar(select(Session))
    assert session is not None
    assert session.revoked_at is not None

    protected_response = protected_client.get("/api/test/protected", headers=auth_headers(token))
    assert protected_response.status_code == 401


def test_logout_without_auth_returns_401(protected_client) -> None:
    response = protected_client.post("/api/auth/logout")
    assert response.status_code == 401


def test_logout_with_invalid_token_returns_401(protected_client) -> None:
    response = protected_client.post(
        "/api/auth/logout",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


def test_last_active_is_throttled(db_session, protected_client) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    raw_token, session = create_session(user)
    initial_last_active = datetime.now(timezone.utc) - timedelta(hours=1)
    session.last_active_at = initial_last_active
    db_session.commit()

    response = protected_client.get("/api/test/protected", headers=auth_headers(raw_token))
    assert response.status_code == 200

    db_session.refresh(session)
    assert session.last_active_at.replace(tzinfo=timezone.utc) > initial_last_active

    updated = session.last_active_at
    second = protected_client.get("/api/test/protected", headers=auth_headers(raw_token))
    assert second.status_code == 200
    db_session.refresh(session)
    assert session.last_active_at.replace(tzinfo=timezone.utc) == updated.replace(tzinfo=timezone.utc)
