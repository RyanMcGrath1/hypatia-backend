"""Authentication service tests."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import func, select

from hypatia.models import AccountEvent, MfaLoginChallenge, Session, User
from hypatia.services.auth.authentication import authenticate_user
from hypatia.services.auth.constants import (
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCESS,
    INVALID_CREDENTIALS_MESSAGE,
)
from hypatia.services.auth.passwords import (
    _DUMMY_PASSWORD_PLAINTEXT,
    perform_dummy_password_verification,
    verify_password,
)
from tests.auth_helpers import create_user


def test_valid_email_and_password_succeed(db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    result = authenticate_user("user@example.com", "validpassword12", ip_address="127.0.0.1")

    assert result.success is True
    assert result.user is not None


def test_wrong_password_fails(db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    result = authenticate_user("user@example.com", "wrongpassword12")

    assert result.success is False
    assert result.user is None


def test_nonexistent_email_fails(db_session) -> None:
    result = authenticate_user("missing@example.com", "validpassword12")

    assert result.success is False
    assert result.user is None


def test_failure_messages_do_not_distinguish_email_vs_password(db_session) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")

    wrong_password = authenticate_user("user@example.com", "wrongpassword12")
    missing_email = authenticate_user("missing@example.com", "validpassword12")

    assert wrong_password.success is missing_email.success is False


def test_inactive_account_cannot_authenticate(db_session) -> None:
    create_user(
        db_session,
        email="inactive@example.com",
        password="validpassword12",
        account_status="inactive",
    )

    result = authenticate_user("inactive@example.com", "validpassword12")

    assert result.success is False


def test_deleted_account_cannot_authenticate(db_session) -> None:
    create_user(
        db_session,
        email="deleted@example.com",
        password="validpassword12",
        account_status="deleted",
    )

    result = authenticate_user("deleted@example.com", "validpassword12")

    assert result.success is False


def test_successful_login_updates_last_login_at(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")
    assert user.last_login_at is None

    authenticate_user("user@example.com", "validpassword12")

    db_session.refresh(user)
    assert user.last_login_at is not None


def test_successful_login_creates_login_success_event(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")

    authenticate_user("user@example.com", "validpassword12", ip_address="203.0.113.10")

    events = db_session.scalars(
        select(AccountEvent).where(AccountEvent.user_id == user.id)
    ).all()
    assert len(events) == 1
    assert events[0].event_type == EVENT_LOGIN_SUCCESS
    assert events[0].ip_address == "203.0.113.10"


def test_failed_login_for_existing_user_creates_login_failed_event(db_session) -> None:
    user = create_user(db_session, email="user@example.com", password="validpassword12")

    authenticate_user("user@example.com", "wrongpassword12", ip_address="198.51.100.5")

    events = db_session.scalars(
        select(AccountEvent).where(AccountEvent.user_id == user.id)
    ).all()
    assert len(events) == 1
    assert events[0].event_type == EVENT_LOGIN_FAILED
    assert events[0].ip_address == "198.51.100.5"


def test_failed_login_for_unknown_email_creates_no_account_event(db_session) -> None:
    authenticate_user("missing@example.com", "validpassword12")

    count = db_session.scalar(select(func.count()).select_from(AccountEvent))
    assert count == 0


def test_successful_login_rehash_updates_password_hash(db_session, monkeypatch) -> None:
    user = create_user(db_session, email="rehash@example.com", password="validpassword12")
    old_hash = user.password_hash

    monkeypatch.setattr(
        "hypatia.services.auth.authentication.password_needs_rehash",
        lambda _stored: True,
    )

    result = authenticate_user("rehash@example.com", "validpassword12")

    assert result.success is True
    db_session.refresh(user)
    assert user.password_hash != old_hash


def test_successful_login_rehash_does_not_update_password_changed_at(
    db_session, monkeypatch
) -> None:
    from datetime import datetime, timezone

    user = create_user(db_session, email="rehash@example.com", password="validpassword12")
    known_changed_at = datetime(2020, 1, 15, 12, 0, tzinfo=timezone.utc)
    user.password_changed_at = known_changed_at
    db_session.commit()

    monkeypatch.setattr(
        "hypatia.services.auth.authentication.password_needs_rehash",
        lambda _stored: True,
    )

    result = authenticate_user("rehash@example.com", "validpassword12")

    assert result.success is True
    db_session.refresh(user)
    assert user.password_changed_at == known_changed_at.replace(tzinfo=None)


def test_invalid_credentials_constant_is_generic() -> None:
    message = INVALID_CREDENTIALS_MESSAGE.lower()
    assert "email" not in message or "or password" in message


# --- Login timing mitigation (Security Finding #7) ---


def test_unknown_email_performs_dummy_password_verification_once(
    db_session, monkeypatch
) -> None:
    calls: list[str] = []

    def _spy(password: str) -> None:
        calls.append(password)
        perform_dummy_password_verification(password)

    monkeypatch.setattr(
        "hypatia.services.auth.authentication.perform_dummy_password_verification",
        _spy,
    )

    with patch(
        "hypatia.services.auth.authentication.verify_password",
        wraps=verify_password,
    ) as real_verify:
        result = authenticate_user("missing@example.com", "any-password-12")

    assert result.success is False
    assert result.user is None
    assert calls == ["any-password-12"]
    assert real_verify.call_count == 0


def test_known_wrong_password_verifies_real_hash_once(db_session, monkeypatch) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")
    dummy_calls: list[str] = []

    monkeypatch.setattr(
        "hypatia.services.auth.authentication.perform_dummy_password_verification",
        lambda password: dummy_calls.append(password),
    )

    with patch(
        "hypatia.services.auth.authentication.verify_password",
        wraps=verify_password,
    ) as real_verify:
        result = authenticate_user("user@example.com", "wrongpassword12")

    assert result.success is False
    assert result.user is None
    assert real_verify.call_count == 1
    assert dummy_calls == []


def test_dummy_password_plaintext_cannot_authenticate_unknown_email(db_session) -> None:
    result = authenticate_user("missing@example.com", _DUMMY_PASSWORD_PLAINTEXT)

    assert result.success is False
    assert result.user is None
    assert result.mfa_required is False
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0
    assert db_session.scalar(select(func.count()).select_from(MfaLoginChallenge)) == 0
    assert db_session.scalar(select(func.count()).select_from(AccountEvent)) == 0


def test_unknown_email_login_has_no_auth_side_effects(db_session) -> None:
    users_before = db_session.scalar(select(func.count()).select_from(User)) or 0

    result = authenticate_user("nobody@example.com", "validpassword12")

    assert result.success is False
    assert result.user is None
    assert result.mfa_required is False
    assert db_session.scalar(select(func.count()).select_from(User)) == users_before
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0
    assert db_session.scalar(select(func.count()).select_from(MfaLoginChallenge)) == 0
    assert db_session.scalar(select(func.count()).select_from(AccountEvent)) == 0


def test_successful_login_does_not_run_dummy_verification(db_session, monkeypatch) -> None:
    create_user(db_session, email="user@example.com", password="validpassword12")
    dummy_calls: list[str] = []

    monkeypatch.setattr(
        "hypatia.services.auth.authentication.perform_dummy_password_verification",
        lambda password: dummy_calls.append(password),
    )

    with patch(
        "hypatia.services.auth.authentication.verify_password",
        wraps=verify_password,
    ) as real_verify:
        result = authenticate_user("user@example.com", "validpassword12")

    assert result.success is True
    assert result.user is not None
    assert real_verify.call_count == 1
    assert dummy_calls == []
