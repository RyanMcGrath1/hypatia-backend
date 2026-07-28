"""Session token generation and storage tests."""

from __future__ import annotations

from sqlalchemy import func, select, text

from hypatia.models import Session
from hypatia.services.auth.sessions import (
    create_session,
    generate_session_token,
    hash_session_token,
)
from tests.auth_helpers import create_user


def test_generated_token_is_non_empty() -> None:
    assert generate_session_token()


def test_generated_tokens_differ_across_calls() -> None:
    assert generate_session_token() != generate_session_token()


def test_raw_token_is_not_stored_in_db(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    raw_token, session = create_session(user)
    db_session.commit()

    assert session.token_hash == hash_session_token(raw_token)
    assert session.token_hash != raw_token

    rows = db_session.execute(text("SELECT token_hash FROM sessions")).fetchall()
    assert all(raw_token not in row[0] for row in rows)


def test_stored_token_hash_matches_hashing_function(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    raw_token, session = create_session(user)
    db_session.commit()

    assert session.token_hash == hash_session_token(raw_token)
