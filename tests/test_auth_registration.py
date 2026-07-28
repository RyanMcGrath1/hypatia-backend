"""Registration service tests."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import func, select

from hypatia.extensions import db
from hypatia.models import AccountEvent, Profile, Session, User
from hypatia.services.auth.authentication import authenticate_user
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_ACTIVE,
    EMAIL_ALREADY_REGISTERED_MESSAGE,
    EVENT_ACCOUNT_CREATED,
    EVENT_LOGIN_SUCCESS,
)
from hypatia.services.auth.passwords import verify_password
from hypatia.services.auth.registration import MAX_NAME_LENGTH, register_user
from hypatia.services.auth.sessions import validate_session


def test_valid_registration_creates_user_and_profile(db_session) -> None:
    result = register_user(
        "user@example.com",
        "validpassword12",
        "Matthew",
        "Thompson",
        ip_address="127.0.0.1",
    )

    assert result.ok is True
    assert result.user is not None
    assert result.raw_token

    user = db_session.scalar(select(User).where(User.email == "user@example.com"))
    profile = db_session.scalar(select(Profile).where(Profile.user_id == user.id))

    assert user is not None
    assert profile is not None
    assert profile.user_id == user.id
    assert profile.first_name == "Matthew"
    assert profile.last_name == "Thompson"
    assert user.email_verified is False
    assert user.account_status == ACCOUNT_STATUS_ACTIVE
    assert user.last_login_at is None
    assert user.password_changed_at is not None
    assert user.password_hash.startswith("$argon2id$")
    assert "validpassword12" not in user.password_hash
    assert verify_password(user.password_hash, "validpassword12")


def test_registration_stores_normalized_email(db_session) -> None:
    result = register_user(
        "  User@Example.COM ",
        "validpassword12",
        "Ada",
        "Lovelace",
    )

    assert result.ok is True
    user = db_session.scalar(select(User))
    assert user is not None
    assert user.email == "user@example.com"


def test_registration_trims_names(db_session) -> None:
    result = register_user(
        "user@example.com",
        "validpassword12",
        "  Matthew  ",
        "  Thompson  ",
    )

    assert result.ok is True
    profile = db_session.scalar(select(Profile))
    assert profile is not None
    assert profile.first_name == "Matthew"
    assert profile.last_name == "Thompson"


def test_login_works_with_different_email_casing_and_whitespace(db_session) -> None:
    register_user("user@example.com", "validpassword12", "Ada", "Lovelace")

    result = authenticate_user("  USER@Example.com ", "validpassword12")

    assert result.success is True


def test_duplicate_normalized_email_rejected(db_session) -> None:
    first = register_user("user@example.com", "validpassword12", "Ada", "Lovelace")
    second = register_user("  USER@example.com ", "anotherpassword12", "Grace", "Hopper")

    assert first.ok is True
    assert second.ok is False
    assert second.conflict is True
    assert second.error == EMAIL_ALREADY_REGISTERED_MESSAGE
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(select(func.count()).select_from(Profile)) == 1


def test_missing_or_invalid_email_rejected(db_session) -> None:
    missing = register_user("", "validpassword12", "Ada", "Lovelace")
    invalid = register_user("not-an-email", "validpassword12", "Ada", "Lovelace")

    assert missing.ok is False
    assert invalid.ok is False
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_missing_or_short_password_rejected(db_session) -> None:
    missing = register_user("user@example.com", "", "Ada", "Lovelace")
    short = register_user("user@example.com", "short", "Ada", "Lovelace")

    assert missing.ok is False
    assert short.ok is False
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_missing_and_whitespace_names_rejected(db_session) -> None:
    missing_first = register_user("a@example.com", "validpassword12", "", "Lovelace")
    missing_last = register_user("b@example.com", "validpassword12", "Ada", "")
    whitespace_first = register_user("c@example.com", "validpassword12", "   ", "Lovelace")
    whitespace_last = register_user("d@example.com", "validpassword12", "Ada", "   ")

    assert missing_first.ok is False
    assert missing_last.ok is False
    assert whitespace_first.ok is False
    assert whitespace_last.ok is False
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_overlong_names_rejected(db_session) -> None:
    too_long = "a" * (MAX_NAME_LENGTH + 1)
    first = register_user("a@example.com", "validpassword12", too_long, "Lovelace")
    last = register_user("b@example.com", "validpassword12", "Ada", too_long)

    assert first.ok is False
    assert last.ok is False
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_duplicate_email_does_not_create_profile(db_session) -> None:
    register_user("user@example.com", "validpassword12", "Ada", "Lovelace")
    register_user("user@example.com", "validpassword12", "Grace", "Hopper")

    assert db_session.scalar(select(func.count()).select_from(Profile)) == 1
    profile = db_session.scalar(select(Profile))
    assert profile is not None
    assert profile.first_name == "Ada"


def test_profile_failure_rolls_back_user(db_session) -> None:
    with patch(
        "hypatia.services.auth.registration.Profile",
        side_effect=RuntimeError("profile boom"),
    ):
        try:
            register_user("user@example.com", "validpassword12", "Ada", "Lovelace")
        except RuntimeError:
            pass

    assert db_session.scalar(select(func.count()).select_from(User)) == 0
    assert db_session.scalar(select(func.count()).select_from(Profile)) == 0


def test_session_failure_rolls_back_user_and_profile(db_session) -> None:
    with patch(
        "hypatia.services.auth.registration.create_session",
        side_effect=RuntimeError("session boom"),
    ):
        try:
            register_user("user@example.com", "validpassword12", "Ada", "Lovelace")
        except RuntimeError:
            pass

    assert db_session.scalar(select(func.count()).select_from(User)) == 0
    assert db_session.scalar(select(func.count()).select_from(Profile)) == 0
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0


def test_successful_registration_creates_account_created_event(db_session) -> None:
    register_user(
        "user@example.com",
        "validpassword12",
        "Ada",
        "Lovelace",
        ip_address="203.0.113.10",
    )

    event = db_session.scalar(select(AccountEvent))
    assert event is not None
    assert event.event_type == EVENT_ACCOUNT_CREATED
    assert event.ip_address == "203.0.113.10"
    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_LOGIN_SUCCESS
        )
    ) == 0


def test_failed_registration_does_not_create_account_created_event(db_session) -> None:
    register_user("user@example.com", "validpassword12", "Ada", "Lovelace")
    register_user("user@example.com", "validpassword12", "Grace", "Hopper")

    assert db_session.scalar(
        select(func.count()).select_from(AccountEvent).where(
            AccountEvent.event_type == EVENT_ACCOUNT_CREATED
        )
    ) == 1


def test_registration_session_token_validates(db_session) -> None:
    result = register_user("user@example.com", "validpassword12", "Ada", "Lovelace")

    validation = validate_session(result.raw_token)
    assert validation.valid is True
    assert validation.user is not None
    assert validation.user.email == "user@example.com"


def test_integrity_error_on_duplicate_email_is_handled(db_session) -> None:
    register_user("user@example.com", "validpassword12", "Ada", "Lovelace")

    with patch(
        "hypatia.services.auth.registration._email_already_registered",
        return_value=False,
    ):
        result = register_user(
            "user@example.com",
            "anotherpassword12",
            "Grace",
            "Hopper",
        )

    assert result.ok is False
    assert result.conflict is True
    assert result.error == EMAIL_ALREADY_REGISTERED_MESSAGE
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db.session.is_active
