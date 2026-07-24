"""GET/PATCH /api/profile tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from hypatia.models import AccountEvent, Profile
from hypatia.services.auth.constants import UNAUTHENTICATED_MESSAGE
from hypatia.services.auth.registration import MAX_NAME_LENGTH
from hypatia.services.auth.sessions import create_session, revoke_session
from hypatia.services.profile import (
    NO_UPDATABLE_FIELDS_MESSAGE,
    PROFILE_UNAVAILABLE_MESSAGE,
)
from tests.auth_helpers import auth_headers, create_user, create_user_with_profile, login


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
        "password": "validpassword12",
        "first_name": "Matthew",
        "last_name": "Thompson",
    }
    defaults.update(user_kwargs)
    user = create_user_with_profile(db_session, **defaults)
    token = login(client, email=defaults["email"], password=defaults["password"])
    return user, token


# --- GET /api/profile ---


def test_get_profile_without_auth_returns_401(client) -> None:
    response = client.get("/api/profile")
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_get_profile_with_revoked_session_returns_401(client, db_session) -> None:
    user = create_user_with_profile(
        db_session,
        email="user@example.com",
        password="validpassword12",
    )
    raw_token, session = create_session(user)
    db_session.commit()
    revoke_session(session)
    db_session.commit()

    response = client.get("/api/profile", headers=auth_headers(raw_token))
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_get_profile_authenticated_returns_expected_fields(client, db_session) -> None:
    changed_at = datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
    user, token = _auth_client_for(
        client,
        db_session,
        first_name="Matthew",
        last_name="Thompson",
        password_changed_at=changed_at,
    )
    db_session.refresh(user)

    response = client.get("/api/profile", headers=auth_headers(token))
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["first_name"] == "Matthew"
    assert payload["last_name"] == "Thompson"
    assert payload["email"] == "user@example.com"
    assert payload["date_joined"] == _iso8601(user.created_at)
    assert payload["password_changed_at"] == _iso8601(changed_at)
    assert payload["totp_enabled"] is False
    assert "user_id" not in payload
    assert "id" not in payload
    assert "password_hash" not in payload
    assert "password" not in payload
    assert "secret_encrypted" not in payload
    assert "provisioning_uri" not in payload
    assert "manual_entry_key" not in payload
    assert "last_used_timecode" not in payload


def test_get_profile_password_changed_at_can_be_null(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session, password_changed_at=None)

    response = client.get("/api/profile", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.get_json()["password_changed_at"] is None


def test_get_profile_missing_profile_returns_clean_error(client, db_session) -> None:
    # User-only account: abnormal state; do not auto-create Profile.
    create_user(db_session, email="orphan@example.com", password="validpassword12")
    token = login(client, email="orphan@example.com", password="validpassword12")

    response = client.get("/api/profile", headers=auth_headers(token))
    assert response.status_code == 500
    assert response.get_json() == {"error": PROFILE_UNAVAILABLE_MESSAGE}
    assert "sql" not in response.get_json()["error"].lower()
    assert "traceback" not in str(response.get_json()).lower()


# --- PATCH /api/profile ---


def test_patch_profile_without_auth_returns_401(client) -> None:
    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt"}),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_patch_first_name_succeeds(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["first_name"] == "Matt"
    assert payload["last_name"] == "Thompson"

    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.first_name == "Matt"
    assert profile.last_name == "Thompson"


def test_patch_last_name_succeeds(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"last_name": "Smith"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.get_json()["last_name"] == "Smith"
    assert response.get_json()["first_name"] == "Matthew"

    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.last_name == "Smith"


def test_patch_both_names_succeeds(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt", "last_name": "Smith"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["first_name"] == "Matt"
    assert payload["last_name"] == "Smith"

    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.first_name == "Matt"
    assert profile.last_name == "Smith"


def test_partial_patch_leaves_omitted_field_unchanged(client, db_session) -> None:
    user, token = _auth_client_for(
        client,
        db_session,
        first_name="Matthew",
        last_name="Thompson",
    )

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.get_json()["last_name"] == "Thompson"

    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.last_name == "Thompson"


def test_patch_trims_whitespace_around_names(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "  Matt  ", "last_name": "  Thompson  "}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.get_json()["first_name"] == "Matt"
    assert response.get_json()["last_name"] == "Thompson"

    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.first_name == "Matt"
    assert profile.last_name == "Thompson"


def test_patch_whitespace_only_first_name_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "   "}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "first_name is required"


def test_patch_whitespace_only_last_name_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"last_name": "\t"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "last_name is required"


def test_patch_name_longer_than_128_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)
    too_long = "a" * (MAX_NAME_LENGTH + 1)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": too_long}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == (
        f"first_name must be at most {MAX_NAME_LENGTH} characters"
    )


def test_patch_non_string_name_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": 123}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "first_name must be a string"


def test_patch_empty_json_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == NO_UPDATABLE_FIELDS_MESSAGE


def test_patch_null_body_rejected(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data="null",
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == NO_UPDATABLE_FIELDS_MESSAGE


def test_patch_unknown_fields_rejected(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    original_email = user.email

    response = client.patch(
        "/api/profile",
        data=json.dumps({"email": "other@example.com"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Unknown field: email"

    db_session.refresh(user)
    assert user.email == original_email


def test_patch_cannot_modify_email(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt", "email": "other@example.com"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Unknown field: email"

    db_session.refresh(user)
    assert user.email == "user@example.com"
    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.first_name == "Matthew"


def test_patch_cannot_modify_user_id(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    other = create_user_with_profile(
        db_session,
        email="other@example.com",
        password="validpassword12",
        first_name="Other",
        last_name="Person",
    )

    response = client.patch(
        "/api/profile",
        data=json.dumps({"user_id": str(other.id), "first_name": "Matt"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Unknown field: user_id"

    profile = db_session.get(Profile, user.id)
    other_profile = db_session.get(Profile, other.id)
    assert profile is not None
    assert other_profile is not None
    assert profile.first_name == "Matthew"
    assert other_profile.first_name == "Other"


def test_patch_response_matches_get_shape_with_updated_values(client, db_session) -> None:
    user, token = _auth_client_for(
        client,
        db_session,
        password_changed_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db_session.refresh(user)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload.keys()) == {
        "first_name",
        "last_name",
        "date_joined",
        "email",
        "password_changed_at",
        "totp_enabled",
    }
    assert payload["first_name"] == "Matt"
    assert payload["last_name"] == "Thompson"
    assert payload["email"] == "user@example.com"
    assert payload["date_joined"] == _iso8601(user.created_at)
    assert payload["password_changed_at"] == _iso8601(user.password_changed_at)
    assert payload["totp_enabled"] is False
    assert "user_id" not in payload
    assert "password_hash" not in payload


def test_patch_does_not_change_user_account_sensitive_fields(client, db_session) -> None:
    user, token = _auth_client_for(
        client,
        db_session,
        password_changed_at=datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc),
    )
    db_session.refresh(user)
    original = {
        "email": user.email,
        "password_hash": user.password_hash,
        "email_verified": user.email_verified,
        "account_status": user.account_status,
        "created_at": user.created_at,
        "password_changed_at": user.password_changed_at,
        "last_login_at": user.last_login_at,
        "updated_at": user.updated_at,
    }

    response = client.patch(
        "/api/profile",
        data=json.dumps({"last_name": "Smith"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    db_session.refresh(user)
    assert user.email == original["email"]
    assert user.password_hash == original["password_hash"]
    assert user.email_verified == original["email_verified"]
    assert user.account_status == original["account_status"]
    assert user.created_at == original["created_at"]
    assert user.password_changed_at == original["password_changed_at"]
    assert user.last_login_at == original["last_login_at"]
    assert user.updated_at == original["updated_at"]


def test_patch_unchanged_values_do_not_churn_profile_updated_at(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    profile = db_session.get(Profile, user.id)
    assert profile is not None
    original_updated_at = profile.updated_at

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matthew", "last_name": "Thompson"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    db_session.refresh(profile)
    assert profile.updated_at == original_updated_at


def test_patch_does_not_create_account_event(client, db_session) -> None:
    _user, token = _auth_client_for(client, db_session)
    # Login may have created LOGIN_SUCCESS; name edits must not add events.
    before_count = len(db_session.scalars(select(AccountEvent)).all())

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    after_count = len(db_session.scalars(select(AccountEvent)).all())
    assert after_count == before_count


def test_authenticated_user_cannot_modify_another_users_profile(client, db_session) -> None:
    user_a, token_a = _auth_client_for(
        client,
        db_session,
        email="a@example.com",
        first_name="Alice",
        last_name="Alpha",
    )
    user_b = create_user_with_profile(
        db_session,
        email="b@example.com",
        password="validpassword12",
        first_name="Bob",
        last_name="Beta",
    )

    response = client.patch(
        "/api/profile",
        data=json.dumps(
            {
                "user_id": str(user_b.id),
                "first_name": "Hacked",
            }
        ),
        content_type="application/json",
        headers=auth_headers(token_a),
    )
    assert response.status_code == 400

    profile_a = db_session.get(Profile, user_a.id)
    profile_b = db_session.get(Profile, user_b.id)
    assert profile_a is not None
    assert profile_b is not None
    assert profile_a.first_name == "Alice"
    assert profile_b.first_name == "Bob"


def test_patch_missing_profile_returns_clean_error(client, db_session) -> None:
    create_user(db_session, email="orphan@example.com", password="validpassword12")
    token = login(client, email="orphan@example.com", password="validpassword12")

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Matt"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 500
    assert response.get_json() == {"error": PROFILE_UNAVAILABLE_MESSAGE}


def test_patch_preserves_internal_spaces_in_names(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    response = client.patch(
        "/api/profile",
        data=json.dumps({"first_name": "Mary Jane", "last_name": "O'Brien"}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.get_json()["first_name"] == "Mary Jane"
    assert response.get_json()["last_name"] == "O'Brien"

    profile = db_session.get(Profile, user.id)
    assert profile is not None
    assert profile.first_name == "Mary Jane"
    assert profile.last_name == "O'Brien"
