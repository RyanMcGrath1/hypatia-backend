"""DELETE /api/account soft-delete / anonymization tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pyotp
import pytest
from sqlalchemy import func, select

from hypatia.models import (
    AccountEvent,
    EmailChangeRequest,
    MfaLoginChallenge,
    Profile,
    Session,
    TOTPMethod,
    User,
)
from hypatia.services.account import (
    ACCOUNT_DELETED_MESSAGE,
    CONFIRMATION_INVALID_MESSAGE,
    CONFIRMATION_REQUIRED_MESSAGE,
    CURRENT_PASSWORD_INCORRECT_MESSAGE,
    TOTP_CODE_NOT_APPLICABLE_MESSAGE,
    TOTP_CODE_REQUIRED_MESSAGE,
    anonymized_deleted_email,
    delete_account,
)
from hypatia.services.account.email_change import (
    generate_email_change_token,
    hash_email_change_token,
)
from hypatia.services.auth.constants import (
    ACCOUNT_STATUS_DELETED,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_LOGIN_SUCCESS,
    INVALID_CREDENTIALS_MESSAGE,
    UNAUTHENTICATED_MESSAGE,
)
from hypatia.services.auth.mfa_challenge import create_mfa_login_challenge
from hypatia.services.auth.passwords import verify_password
from hypatia.services.auth.sessions import (
    create_session,
    hash_session_token,
    revoke_session,
    validate_session,
)
from hypatia.services.email import EmailDeliveryError
from hypatia.services.security.totp import TOTP_INVALID_CODE_MESSAGE
from tests.auth_helpers import auth_headers, create_user_with_profile, login

PASSWORD = "validpassword12"
ORIGINAL_EMAIL = "user@example.com"


def _auth_client(client, db_session, **user_kwargs):
    defaults = {
        "email": ORIGINAL_EMAIL,
        "password": PASSWORD,
        "first_name": "Matthew",
        "last_name": "Thompson",
    }
    defaults.update(user_kwargs)
    user = create_user_with_profile(db_session, **defaults)
    token = login(client, email=defaults["email"], password=defaults["password"])
    return user, token


def _delete(client, token: str, *, current_password: str = PASSWORD, confirmation: str = "DELETE", **extra):
    body = {
        "current_password": current_password,
        "confirmation": confirmation,
    }
    body.update(extra)
    return client.delete(
        "/api/account",
        data=json.dumps(body),
        content_type="application/json",
        headers=auth_headers(token),
    )


def _current_code(secret: str, *, for_time: float | None = None) -> str:
    totp = pyotp.TOTP(secret, digits=6, interval=30)
    if for_time is None:
        return totp.now()
    return totp.at(for_time)


def _enroll_totp(client, db_session, user, token: str) -> tuple[str, str]:
    setup = client.post(
        "/api/security/totp/setup",
        data=json.dumps({"current_password": PASSWORD}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert setup.status_code == 200
    secret = setup.get_json()["manual_entry_key"]
    enabled = client.post(
        "/api/security/totp/enable",
        data=json.dumps({"code": _current_code(secret)}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert enabled.status_code == 200
    db_session.refresh(user)
    return secret, enabled.get_json()["token"]


def _event_count(db_session, *, user_id, event_type: str) -> int:
    return db_session.scalar(
        select(func.count())
        .select_from(AccountEvent)
        .where(
            AccountEvent.user_id == user_id,
            AccountEvent.event_type == event_type,
        )
    )


def _add_email_change_request(db_session, user: User, *, completed: bool = False) -> EmailChangeRequest:
    now = datetime.now(timezone.utc)
    old_raw = generate_email_change_token()
    new_raw = generate_email_change_token()
    row = EmailChangeRequest(
        user_id=user.id,
        old_email=user.email,
        new_email="pending-new@example.com",
        old_email_token_hash=hash_email_change_token(old_raw),
        new_email_token_hash=hash_email_change_token(new_raw),
        created_at=now,
        expires_at=now + timedelta(hours=24),
        completed_at=now if completed else None,
        old_email_confirmed_at=now if completed else None,
        new_email_confirmed_at=now if completed else None,
    )
    db_session.add(row)
    db_session.commit()
    return row


# --- Authentication ---


def test_delete_without_auth_returns_401(client) -> None:
    response = client.delete(
        "/api/account",
        data=json.dumps(
            {"current_password": PASSWORD, "confirmation": "DELETE"}
        ),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == UNAUTHENTICATED_MESSAGE


def test_delete_with_invalid_session_returns_401(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    session = db_session.scalar(
        select(Session).where(Session.token_hash == hash_session_token(token))
    )
    revoke_session(session)
    db_session.commit()

    response = _delete(client, token)
    assert response.status_code == 401
    assert response.get_json()["error"] == UNAUTHENTICATED_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"
    assert user.deleted_at is None


def test_valid_active_account_reaches_delete_flow(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    with patch("hypatia.services.account.delete.send_email") as send_email:
        response = _delete(client, token)
    assert response.status_code == 200
    assert response.get_json()["message"] == ACCOUNT_DELETED_MESSAGE
    db_session.refresh(user)
    assert user.account_status == ACCOUNT_STATUS_DELETED
    send_email.assert_called_once()


# --- Confirmation ---


def test_missing_confirmation_returns_400(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    response = client.delete(
        "/api/account",
        data=json.dumps({"current_password": PASSWORD}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == CONFIRMATION_REQUIRED_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 0


def test_incorrect_confirmation_returns_400(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    for bad in ("delete", "Delete", " DELETE", "DELETE ", "REMOVE"):
        response = _delete(client, token, confirmation=bad)
        assert response.status_code == 400
        assert response.get_json()["error"] == CONFIRMATION_INVALID_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"
    assert user.email == ORIGINAL_EMAIL
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 0


def test_exact_delete_confirmation_accepted(client, db_session) -> None:
    _user, token = _auth_client(client, db_session)
    with patch("hypatia.services.account.delete.send_email"):
        response = _delete(client, token, confirmation="DELETE")
    assert response.status_code == 200


# --- Password ---


def test_incorrect_password_does_not_mutate(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    original_hash = user.password_hash
    with patch("hypatia.services.account.delete.send_email") as send_email:
        response = _delete(client, token, current_password="wrongpassword123")
    assert response.status_code == 400
    assert response.get_json()["error"] == CURRENT_PASSWORD_INCORRECT_MESSAGE

    db_session.refresh(user)
    assert user.password_hash == original_hash
    assert user.account_status == "active"
    assert user.deleted_at is None
    assert user.email == ORIGINAL_EMAIL
    assert db_session.get(Profile, user.id) is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        )
        >= 1
    )
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 0
    send_email.assert_not_called()


# --- TOTP disabled ---


def test_delete_without_totp_succeeds(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    assert user.totp_method is None
    with patch("hypatia.services.account.delete.send_email"):
        response = _delete(client, token)
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.account_status == ACCOUNT_STATUS_DELETED


def test_totp_code_rejected_when_totp_disabled(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    response = _delete(client, token, totp_code="123456")
    assert response.status_code == 400
    assert response.get_json()["error"] == TOTP_CODE_NOT_APPLICABLE_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"


# --- TOTP enabled ---


def test_totp_enabled_missing_code_rejected(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _secret, new_token = _enroll_totp(client, db_session, user, token)
    response = _delete(client, new_token)
    assert response.status_code == 400
    assert response.get_json()["error"] == TOTP_CODE_REQUIRED_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"
    assert db_session.get(TOTPMethod, user.id) is not None


def test_totp_enabled_invalid_code_rejected(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _secret, new_token = _enroll_totp(client, db_session, user, token)
    original_hash = user.password_hash
    response = _delete(client, new_token, totp_code="000000")
    assert response.status_code == 400
    assert response.get_json()["error"] == TOTP_INVALID_CODE_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"
    assert user.password_hash == original_hash
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 0


def test_totp_enabled_replayed_code_rejected(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_totp(client, db_session, user, token)
    method = db_session.get(TOTPMethod, user.id)
    assert method.last_used_timecode is not None
    # Reuse the already-consumed enable-step code within the same window.
    code = _current_code(secret)
    # Force last_used to current timecode so any current-window code is replay.
    method.last_used_timecode = int(datetime.now(timezone.utc).timestamp()) // 30 + 1
    db_session.commit()

    response = _delete(client, new_token, totp_code=code)
    assert response.status_code == 400
    assert response.get_json()["error"] == TOTP_INVALID_CODE_MESSAGE
    db_session.refresh(user)
    assert user.account_status == "active"


def test_totp_enabled_valid_password_and_code_succeeds(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_totp(client, db_session, user, token)
    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch("hypatia.services.account.delete.send_email"):
            response = _delete(client, new_token, totp_code=code)
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.account_status == ACCOUNT_STATUS_DELETED
    assert db_session.get(TOTPMethod, user.id) is None


# --- Tombstone / personal / security data ---


def test_user_tombstone_and_anonymization(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    user_id = user.id
    original_hash = user.password_hash
    with patch("hypatia.services.account.delete.send_email"):
        assert _delete(client, token).status_code == 200

    db_session.refresh(user)
    assert user.account_status == ACCOUNT_STATUS_DELETED
    assert user.deleted_at is not None
    assert user.email_verified is False
    assert user.email == anonymized_deleted_email(user_id)
    assert ORIGINAL_EMAIL not in user.email
    assert user.email.endswith("@deleted.invalid")
    assert user.password_hash != original_hash
    assert verify_password(user.password_hash, PASSWORD) is False
    assert db_session.get(User, user_id) is not None


def test_profile_and_security_rows_removed(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_totp(client, db_session, user, token)
    create_mfa_login_challenge(user)
    db_session.commit()
    _add_email_change_request(db_session, user, completed=False)
    _add_email_change_request(db_session, user, completed=True)
    extra_raw, _ = create_session(user)
    db_session.commit()

    assert db_session.get(Profile, user.id) is not None
    assert db_session.get(TOTPMethod, user.id) is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        >= 1
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EmailChangeRequest)
            .where(EmailChangeRequest.user_id == user.id)
        )
        == 2
    )

    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch("hypatia.services.account.delete.send_email"):
            assert _delete(client, new_token, totp_code=code).status_code == 200

    assert db_session.get(Profile, user.id) is None
    assert db_session.get(TOTPMethod, user.id) is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EmailChangeRequest)
            .where(EmailChangeRequest.user_id == user.id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        )
        == 0
    )
    assert validate_session(new_token).valid is False
    assert validate_session(extra_raw).valid is False


# --- Audit ---


def test_account_deleted_event_and_prior_events_preserved(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    db_session.add(
        AccountEvent(
            user_id=user.id,
            event_type=EVENT_ACCOUNT_CREATED,
            ip_address="127.0.0.1",
        )
    )
    db_session.commit()
    prior = _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_CREATED)
    assert prior >= 1
    login_events_before = _event_count(
        db_session, user_id=user.id, event_type=EVENT_LOGIN_SUCCESS
    )

    with patch("hypatia.services.account.delete.send_email"):
        assert _delete(client, token).status_code == 200

    assert (
        _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_CREATED)
        == prior
    )
    assert (
        _event_count(db_session, user_id=user.id, event_type=EVENT_LOGIN_SUCCESS)
        == login_events_before
    )
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 1

    event = db_session.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_ACCOUNT_DELETED,
        )
    )
    assert event is not None
    assert event.ip_address is not None
    assert event.created_at is not None


def test_failed_deletion_creates_no_account_deleted_event(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    assert _delete(client, token, confirmation="delete").status_code == 400
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 0


# --- Email notification ---


def test_deletion_notification_to_original_email(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    with patch("hypatia.services.account.delete.send_email") as send_email:
        assert _delete(client, token).status_code == 200

    send_email.assert_called_once()
    kwargs = send_email.call_args.kwargs
    assert kwargs["to_address"] == ORIGINAL_EMAIL
    assert "deleted" in kwargs["subject"].lower()
    body = kwargs["text_body"]
    assert "deleted" in body.lower()
    assert PASSWORD not in body
    assert token not in body
    assert "totp" not in body.lower()


def test_notification_only_after_successful_deletion(client, db_session) -> None:
    _user, token = _auth_client(client, db_session)
    with patch("hypatia.services.account.delete.send_email") as send_email:
        assert _delete(client, token, current_password="wrongpassword123").status_code == 400
    send_email.assert_not_called()


def test_email_failure_does_not_restore_account(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    with patch(
        "hypatia.services.account.delete.send_email",
        side_effect=EmailDeliveryError("smtp down"),
    ):
        response = _delete(client, token)
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.account_status == ACCOUNT_STATUS_DELETED
    assert user.deleted_at is not None
    assert db_session.get(Profile, user.id) is None


# --- Post-deletion ---


def test_old_session_and_login_fail_after_deletion(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    with patch("hypatia.services.account.delete.send_email"):
        assert _delete(client, token).status_code == 200

    profile = client.get("/api/profile", headers=auth_headers(token))
    assert profile.status_code == 401
    assert profile.get_json()["error"] == UNAUTHENTICATED_MESSAGE

    login_response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": ORIGINAL_EMAIL, "password": PASSWORD}),
        content_type="application/json",
    )
    assert login_response.status_code == 401
    assert login_response.get_json()["error"] == INVALID_CREDENTIALS_MESSAGE

    db_session.refresh(user)
    anon_login = client.post(
        "/api/auth/login",
        data=json.dumps({"email": user.email, "password": PASSWORD}),
        content_type="application/json",
    )
    assert anon_login.status_code == 401


def test_repeated_delete_with_old_token_returns_401(client, db_session) -> None:
    _user, token = _auth_client(client, db_session)
    with patch("hypatia.services.account.delete.send_email"):
        assert _delete(client, token).status_code == 200
    second = _delete(client, token)
    assert second.status_code == 401
    assert second.get_json()["error"] == UNAUTHENTICATED_MESSAGE


def test_original_email_can_register_new_account(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    tombstone_id = user.id
    with patch("hypatia.services.account.delete.send_email"):
        assert _delete(client, token).status_code == 200

    register = client.post(
        "/api/auth/register",
        data=json.dumps(
            {
                "email": ORIGINAL_EMAIL,
                "password": "brandnewpassword1",
                "first_name": "Ada",
                "last_name": "Lovelace",
            }
        ),
        content_type="application/json",
    )
    assert register.status_code == 201
    new_user = db_session.scalar(select(User).where(User.email == ORIGINAL_EMAIL))
    assert new_user is not None
    assert new_user.id != tombstone_id
    assert db_session.get(Profile, new_user.id) is not None

    tombstone = db_session.get(User, tombstone_id)
    assert tombstone is not None
    assert tombstone.account_status == ACCOUNT_STATUS_DELETED
    assert db_session.get(Profile, tombstone_id) is None


# --- Transaction safety ---


def test_database_failure_during_deletion_rolls_back(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    session = db_session.scalar(
        select(Session).where(Session.token_hash == hash_session_token(token))
    )
    original_hash = user.password_hash

    with patch(
        "hypatia.services.account.delete.revoke_all_sessions_for_user",
        side_effect=RuntimeError("boom"),
    ):
        with patch("hypatia.services.account.delete.send_email") as send_email:
            with pytest.raises(RuntimeError):
                delete_account(
                    user,
                    session,
                    current_password=PASSWORD,
                    confirmation="DELETE",
                )
            send_email.assert_not_called()

    db_session.refresh(user)
    assert user.account_status == "active"
    assert user.deleted_at is None
    assert user.email == ORIGINAL_EMAIL
    assert user.password_hash == original_hash
    assert db_session.get(Profile, user.id) is not None
    assert session.revoked_at is None
    assert validate_session(token).valid is True
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_ACCOUNT_DELETED) == 0
