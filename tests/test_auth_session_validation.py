"""Session validation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypatia.services.auth.sessions import (
    create_session,
    hash_session_token,
    revoke_session,
    validate_session,
)
from tests.auth_helpers import create_user


def test_valid_token_authenticates(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    raw_token, _session = create_session(user)
    db_session.commit()

    result = validate_session(raw_token)

    assert result.valid is True
    assert result.user is not None
    assert result.user.id == user.id
    assert result.session is not None


def test_nonexistent_token_fails(db_session) -> None:
    result = validate_session("not-a-real-token")
    assert result.valid is False


def test_revoked_token_fails(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    raw_token, session = create_session(user)
    revoke_session(session)
    db_session.commit()

    result = validate_session(raw_token)
    assert result.valid is False


def test_expired_token_fails(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    raw_token, session = create_session(user)
    session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    result = validate_session(raw_token)
    assert result.valid is False


def test_session_for_inactive_user_fails(db_session) -> None:
    user = create_user(
        db_session,
        email="inactive@example.com",
        password="validpassword12",
        account_status="inactive",
    )
    raw_token, _session = create_session(user)
    db_session.commit()

    result = validate_session(raw_token)
    assert result.valid is False
