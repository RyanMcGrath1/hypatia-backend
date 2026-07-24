"""POST /api/account/change-password tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import func, select

from hypatia.models import AccountEvent, Session, User
from hypatia.services.account import change_user_password
from hypatia.services.auth.constants import (
    EVENT_PASSWORD_CHANGED,
    UNAUTHENTICATED_MESSAGE,
)
from hypatia.services.auth.passwords import verify_password
from hypatia.services.auth.sessions import (
    create_session,
    revoke_session,
    validate_session,
)
from hypatia.services.auth.validation import MIN_PASSWORD_LENGTH, validate_password
from tests.auth_helpers import auth_headers, create_user_with_profile, login

OLD_PASSWORD = "validpassword12"
NEW_PASSWORD = "brandnewpassword1"


def _iso8601(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0).isoformat()


def _auth_client_for(client, db_session, **user_kwargs):
    defaults = {
        "email": "user@example.com",
        "password": OLD_PASSWORD,
        "first_name": "Matthew",
        "last_name": "Thompson",
    }
    defaults.update(user_kwargs)
    user = create_user_with_profile(db_session, **defaults)
    token = login(client, email=defaults["email"], password=defaults["password"])
    return user, token


def _change_password(
    client,
    token: str,
    *,
    current_password: str = OLD_PASSWORD,
    new_password: str = NEW_PASSWORD,
    confirm_new_password: str | None = None,
):
    if confirm_new_password is None:
        confirm_new_password = new_password
    return client.post(
        "/api/account/change-password",
        data=json.dumps(
            {
                "current_password": current_password,
                "new_password": new_password,
                "confirm_new_password": confirm_new_password,
            }
        ),
        content_type="application/json",
        headers=auth_headers(token),
    )


# --- Shared password policy (registration + validator) ---


def test_shared_password_minimum_is_fifteen() -> None:
    assert MIN_PASSWORD_LENGTH == 15


def test_fourteen_character_new_password_rejected_by_validator() -> None:
    assert validate_password("a" * 14).ok is False


def test_fifteen_character_new_password_accepted_by_validator() -> None:
    assert validate_password("a" * 15).ok is True


def test_registration_uses_fifteen_character_minimum(client, db_session) -> None:
    response = client.post(
        "/api/auth/register",
        data=json.dumps(
            {
                "email": "new@example.com",
                "password": "a" * 14,
                "first_name": "Ada",
                "last_name": "Lovelace",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "15" in response.get_json()["error"]
    assert db_session.scalar(select(func.count()).select_from(User)) == 0

    ok = client.post(
        "/api/auth/register",
        data=json.dumps(
            {
                "email": "new@example.com",
                "password": "a" * 15,
                "first_name": "Ada",
                "last_name": "Lovelace",
            }
        ),
        content_type="application/json",
    )
    assert ok.status_code == 201


def test_spaces_remain_allowed_and_passwords_are_not_stripped() -> None:
    with_spaces = " fifteen chars "
    assert len(with_spaces) == 15
    assert validate_password(with_spaces).ok is True

    leading = " 12345678901234"
    assert len(leading) == 15
    assert validate_password(leading).ok is True
    assert validate_password(leading.lstrip()).ok is False


# --- Authentication ---


def test_change_password_without_auth_returns_401(client) -> None:
    response = client.post(
        "/api/account/change-password",
        data=json.dumps(
            {
                "current_password": OLD_PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_new_password": NEW_PASSWORD,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_change_password_with_revoked_token_returns_401(client, db_session) -> None:
    user = create_user_with_profile(
        db_session,
        email="user@example.com",
        password=OLD_PASSWORD,
    )
    raw_token, session = create_session(user)
    db_session.commit()
    revoke_session(session)
    db_session.commit()

    response = _change_password(client, raw_token)
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


# --- Current password ---


def test_correct_current_password_succeeds(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    response = _change_password(client, token)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Password changed successfully"
    assert payload["token"]
    assert payload["password_changed_at"]


def test_incorrect_current_password_fails_without_side_effects(client, db_session) -> None:
    user, token = _auth_client_for(
        client,
        db_session,
        password_changed_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    db_session.refresh(user)
    original_hash = user.password_hash
    original_changed_at = user.password_changed_at

    other_token, other_session = create_session(user)
    db_session.commit()

    response = _change_password(client, token, current_password="wrongpassword12")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Current password is incorrect"}

    db_session.refresh(user)
    db_session.refresh(other_session)
    assert user.password_hash == original_hash
    assert user.password_changed_at == original_changed_at
    assert other_session.revoked_at is None
    assert validate_session(token).valid is True
    assert validate_session(other_token).valid is True
    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_PASSWORD_CHANGED
        )
    ) == 0


# --- Confirmation ---


def test_mismatched_confirmation_rejected_without_side_effects(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    db_session.refresh(user)
    original_hash = user.password_hash
    original_changed_at = user.password_changed_at

    response = _change_password(
        client,
        token,
        new_password=NEW_PASSWORD,
        confirm_new_password="differentpassword1",
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "New passwords do not match"}

    db_session.refresh(user)
    assert user.password_hash == original_hash
    assert user.password_changed_at == original_changed_at
    assert validate_session(token).valid is True
    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_PASSWORD_CHANGED
        )
    ) == 0


def test_fourteen_character_new_password_rejected_on_endpoint(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    db_session.refresh(user)
    original_hash = user.password_hash

    short = "a" * 14
    response = _change_password(
        client,
        token,
        new_password=short,
        confirm_new_password=short,
    )
    assert response.status_code == 400
    assert "15" in response.get_json()["error"]

    db_session.refresh(user)
    assert user.password_hash == original_hash


def test_new_password_with_spaces_accepted(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)
    spaced = " fifteen chars "
    assert len(spaced) == 15

    response = _change_password(
        client,
        token,
        new_password=spaced,
        confirm_new_password=spaced,
    )
    assert response.status_code == 200

    user = db_session.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    assert verify_password(user.password_hash, spaced)
    assert not verify_password(user.password_hash, spaced.strip())


# --- Password update ---


def test_valid_change_replaces_hash_and_updates_timestamp(client, db_session) -> None:
    known_changed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    user, token = _auth_client_for(
        client,
        db_session,
        password_changed_at=known_changed_at,
    )
    db_session.refresh(user)
    original_hash = user.password_hash

    before = datetime.now(timezone.utc)
    response = _change_password(client, token)
    after = datetime.now(timezone.utc)
    assert response.status_code == 200
    payload = response.get_json()

    db_session.refresh(user)
    assert user.password_hash != original_hash
    assert user.password_hash.startswith("$argon2id$")
    assert NEW_PASSWORD not in user.password_hash
    assert OLD_PASSWORD not in user.password_hash
    assert verify_password(user.password_hash, NEW_PASSWORD)
    assert not verify_password(user.password_hash, OLD_PASSWORD)

    assert user.password_changed_at is not None
    changed = user.password_changed_at
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=timezone.utc)
    else:
        changed = changed.astimezone(timezone.utc)
    assert _iso8601(changed) != _iso8601(known_changed_at)
    assert before <= changed <= after
    assert payload["password_changed_at"] == _iso8601(user.password_changed_at)


# --- Sessions ---


def test_password_change_revokes_all_sessions_and_returns_valid_replacement(
    client, db_session
) -> None:
    user, current_token = _auth_client_for(client, db_session)
    other_token_a, _ = create_session(user)
    other_token_b, _ = create_session(user)
    db_session.commit()

    response = _change_password(client, current_token)
    assert response.status_code == 200
    new_token = response.get_json()["token"]
    assert new_token != current_token

    assert validate_session(current_token).valid is False
    assert validate_session(other_token_a).valid is False
    assert validate_session(other_token_b).valid is False
    assert validate_session(new_token).valid is True

    active = db_session.scalars(
        select(Session).where(
            Session.user_id == user.id,
            Session.revoked_at.is_(None),
        )
    ).all()
    assert len(active) == 1

    profile = client.get("/api/profile", headers=auth_headers(new_token))
    assert profile.status_code == 200

    for old in (current_token, other_token_a, other_token_b):
        denied = client.get("/api/profile", headers=auth_headers(old))
        assert denied.status_code == 401


# --- Account events ---


def test_successful_change_creates_password_changed_event(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = _change_password(client, token)
    assert response.status_code == 200

    events = db_session.scalars(
        select(AccountEvent).where(AccountEvent.event_type == EVENT_PASSWORD_CHANGED)
    ).all()
    assert len(events) == 1
    assert events[0].user_id == user.id
    assert events[0].created_at is not None


def test_failed_change_does_not_create_password_changed_event(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    _change_password(client, token, current_password="wrongpassword12")
    _change_password(
        client,
        token,
        new_password=NEW_PASSWORD,
        confirm_new_password="mismatchpassword1",
    )
    _change_password(
        client,
        token,
        new_password="a" * 14,
        confirm_new_password="a" * 14,
    )

    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_PASSWORD_CHANGED
        )
    ) == 0


# --- Transaction safety ---


def test_failure_during_replacement_session_rolls_back(client, db_session) -> None:
    user, token = _auth_client_for(
        client,
        db_session,
        password_changed_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db_session.refresh(user)
    original_hash = user.password_hash
    original_changed_at = user.password_changed_at
    current_session = validate_session(token).session
    assert current_session is not None
    other_token, _other_session = create_session(user)
    db_session.commit()

    with patch(
        "hypatia.services.account.password.create_session",
        side_effect=RuntimeError("simulated failure"),
    ):
        try:
            change_user_password(
                user,
                current_session,
                current_password=OLD_PASSWORD,
                new_password=NEW_PASSWORD,
                confirm_new_password=NEW_PASSWORD,
            )
        except RuntimeError:
            pass

    db_session.expire_all()
    user = db_session.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    assert user.password_hash == original_hash
    assert user.password_changed_at == original_changed_at
    assert verify_password(user.password_hash, OLD_PASSWORD)
    assert validate_session(token).valid is True
    assert validate_session(other_token).valid is True
    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_PASSWORD_CHANGED
        )
    ) == 0


# --- Profile compatibility ---


def test_profile_exposes_updated_password_changed_at(client, db_session) -> None:
    user, token = _auth_client_for(
        client,
        db_session,
        password_changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    change = _change_password(client, token)
    assert change.status_code == 200
    new_token = change.get_json()["token"]
    reported = change.get_json()["password_changed_at"]

    profile = client.get("/api/profile", headers=auth_headers(new_token))
    assert profile.status_code == 200
    assert profile.get_json()["password_changed_at"] == reported

    db_session.refresh(user)
    assert profile.get_json()["password_changed_at"] == _iso8601(user.password_changed_at)


def test_missing_fields_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)
    response = client.post(
        "/api/account/change-password",
        data=json.dumps({"current_password": OLD_PASSWORD}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "new_password is required"
