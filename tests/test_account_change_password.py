"""POST /api/account/change-password tests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from unittest.mock import patch

import pyotp
from sqlalchemy import func, select

from hypatia.models import (
    AccountEvent,
    EmailChangeRequest,
    MfaLoginChallenge,
    Session,
    TOTPMethod,
    User,
)
from hypatia.services.account import (
    INVALID_VERIFICATION_TOKEN_MESSAGE,
    change_user_password,
)
from hypatia.services.auth.constants import (
    EVENT_LOGIN_SUCCESS,
    EVENT_PASSWORD_CHANGED,
    INVALID_CREDENTIALS_MESSAGE,
    UNAUTHENTICATED_MESSAGE,
)
from hypatia.services.auth.mfa_challenge import (
    create_mfa_login_challenge,
    hash_mfa_challenge_token,
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
NEW_EMAIL = "new@example.com"
_TOKEN_RE = re.compile(r"token=([^\s&]+)")


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


def _enroll_totp(client, db_session, user, token: str) -> tuple[str, str]:
    """Setup + enable TOTP; return (plaintext_secret, new_session_token)."""
    setup = client.post(
        "/api/security/totp/setup",
        data=json.dumps({"current_password": OLD_PASSWORD}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert setup.status_code == 200
    secret = setup.get_json()["manual_entry_key"]
    code = pyotp.TOTP(secret, digits=6, interval=30).now()
    enabled = client.post(
        "/api/security/totp/enable",
        data=json.dumps({"code": code}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert enabled.status_code == 200
    db_session.refresh(user)
    return secret, enabled.get_json()["token"]


def _password_login_challenge(client, *, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": email, "password": password}),
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload.get("mfa_required") is True
    assert "token" not in payload
    challenge = payload.get("challenge_token")
    assert isinstance(challenge, str) and challenge
    return challenge


def _valid_totp_code(db_session, user, secret: str) -> tuple[str, float]:
    """Return a TOTP code and mocked time that avoid last_used_timecode replay."""
    method = db_session.get(TOTPMethod, user.id)
    assert method is not None
    assert method.last_used_timecode is not None
    next_time = (method.last_used_timecode + 1) * 30 + 1
    return pyotp.TOTP(secret).at(next_time), float(next_time)


def _complete_totp(client, *, challenge_token: str, code: str):
    return client.post(
        "/api/auth/login/totp",
        data=json.dumps({"challenge_token": challenge_token, "code": code}),
        content_type="application/json",
    )


def _change_email(
    client,
    token: str,
    *,
    new_email: str = NEW_EMAIL,
    current_password: str = OLD_PASSWORD,
):
    return client.post(
        "/api/account/change-email",
        data=json.dumps(
            {
                "new_email": new_email,
                "current_password": current_password,
            }
        ),
        content_type="application/json",
        headers=auth_headers(token),
    )


def _verify_email_change(client, raw_token: str):
    return client.post(
        "/api/account/change-email/verify",
        data=json.dumps({"token": raw_token}),
        content_type="application/json",
    )


def _extract_email_change_token(text: str) -> str:
    match = _TOKEN_RE.search(text)
    assert match is not None, f"token not found in email body: {text!r}"
    return match.group(1)


def _email_change_tokens_from_send_mock(mock_send) -> tuple[str, str]:
    calls = mock_send.call_args_list
    assert len(calls) >= 2
    old_body = calls[0].kwargs["text_body"]
    new_body = calls[1].kwargs["text_body"]
    return _extract_email_change_token(old_body), _extract_email_change_token(new_body)


def _email_change_request_count(db_session, user_id) -> int:
    return db_session.scalar(
        select(func.count())
        .select_from(EmailChangeRequest)
        .where(EmailChangeRequest.user_id == user_id)
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
    challenge_token = create_mfa_login_challenge(user)
    db_session.commit()
    challenge_hash = hash_mfa_challenge_token(challenge_token)

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, new_raw = _email_change_tokens_from_send_mock(mock_send)
    assert _email_change_request_count(db_session, user.id) == 1

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
    # MFA challenge invalidation must roll back with the password change.
    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(MfaLoginChallenge.token_hash == challenge_hash)
        )
        is not None
    )
    # Pending email-change cleanup must also roll back.
    assert _email_change_request_count(db_session, user.id) == 1
    old_verify = _verify_email_change(client, old_raw)
    assert old_verify.status_code == 200
    assert old_verify.get_json()["email_change_complete"] is False
    new_verify = _verify_email_change(client, new_raw)
    assert new_verify.status_code == 200
    assert new_verify.get_json()["email_change_complete"] is True
    db_session.refresh(user)
    assert user.email == NEW_EMAIL


# --- MFA login challenge invalidation ---


def test_password_change_invalidates_outstanding_mfa_challenge(client, db_session) -> None:
    """Audit finding: old MFA challenge must not mint a Session after password change."""
    user, token = _auth_client_for(client, db_session)
    secret, session_token = _enroll_totp(client, db_session, user, token)

    for event in list(
        db_session.scalars(
            select(AccountEvent).where(AccountEvent.user_id == user.id)
        ).all()
    ):
        if event.event_type == EVENT_LOGIN_SUCCESS:
            db_session.delete(event)
    db_session.commit()

    challenge = _password_login_challenge(
        client, email="user@example.com", password=OLD_PASSWORD
    )
    sessions_before = db_session.scalar(
        select(func.count())
        .select_from(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
    )

    change = _change_password(client, session_token)
    assert change.status_code == 200
    payload = change.get_json()
    assert set(payload.keys()) == {"message", "token", "password_changed_at"}
    assert payload["message"] == "Password changed successfully"
    assert payload["token"]
    assert payload["password_changed_at"]

    code, mocked_time = _valid_totp_code(db_session, user, secret)
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=mocked_time,
    ):
        complete = _complete_totp(client, challenge_token=challenge, code=code)

    assert complete.status_code == 401
    assert complete.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}
    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(
                MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge)
            )
        )
        is None
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        )
        == 1
    )
    # Replacement session from password change only — not from the old challenge.
    assert sessions_before == 1
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AccountEvent)
            .where(
                AccountEvent.user_id == user.id,
                AccountEvent.event_type == EVENT_LOGIN_SUCCESS,
            )
        )
        == 0
    )


def test_password_change_invalidates_all_outstanding_mfa_challenges(
    client, db_session
) -> None:
    user, token = _auth_client_for(client, db_session)
    secret, session_token = _enroll_totp(client, db_session, user, token)

    challenge_a = _password_login_challenge(
        client, email="user@example.com", password=OLD_PASSWORD
    )
    challenge_b = _password_login_challenge(
        client, email="user@example.com", password=OLD_PASSWORD
    )
    assert challenge_a != challenge_b
    # Single-active challenge: a second password login replaces A with B.
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        == 1
    )
    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(
                MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge_a)
            )
        )
        is None
    )
    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(
                MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge_b)
            )
        )
        is not None
    )

    change = _change_password(client, session_token)
    assert change.status_code == 200

    code, mocked_time = _valid_totp_code(db_session, user, secret)
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=mocked_time,
    ):
        for challenge in (challenge_a, challenge_b):
            complete = _complete_totp(client, challenge_token=challenge, code=code)
            assert complete.status_code == 401
            assert complete.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}

    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        == 0
    )


def test_password_change_does_not_invalidate_other_users_mfa_challenge(
    client, db_session
) -> None:
    user_a, token_a = _auth_client_for(
        client,
        db_session,
        email="usera@example.com",
    )
    _secret_a, session_a = _enroll_totp(client, db_session, user_a, token_a)

    user_b, token_b = _auth_client_for(
        client,
        db_session,
        email="userb@example.com",
    )
    secret_b, _session_b = _enroll_totp(client, db_session, user_b, token_b)
    challenge_b = _password_login_challenge(
        client, email="userb@example.com", password=OLD_PASSWORD
    )

    change = _change_password(client, session_a)
    assert change.status_code == 200

    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(
                MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge_b)
            )
        )
        is not None
    )

    code, mocked_time = _valid_totp_code(db_session, user_b, secret_b)
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=mocked_time,
    ):
        complete = _complete_totp(client, challenge_token=challenge_b, code=code)
    assert complete.status_code == 200
    assert validate_session(complete.get_json()["token"]).valid is True


def test_normal_totp_login_still_works_without_password_change(
    client, db_session
) -> None:
    user, token = _auth_client_for(client, db_session)
    secret, _session_token = _enroll_totp(client, db_session, user, token)
    challenge = _password_login_challenge(
        client, email="user@example.com", password=OLD_PASSWORD
    )

    code, mocked_time = _valid_totp_code(db_session, user, secret)
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=mocked_time,
    ):
        complete = _complete_totp(client, challenge_token=challenge, code=code)

    assert complete.status_code == 200
    assert validate_session(complete.get_json()["token"]).valid is True


# --- Pending email-change invalidation ---


def test_password_change_invalidates_unconfirmed_email_change_tokens(
    client, db_session
) -> None:
    """Audit finding: outstanding email-change tokens must fail after password change."""
    user, token = _auth_client_for(client, db_session)
    original_email = user.email

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, new_raw = _email_change_tokens_from_send_mock(mock_send)
    assert _email_change_request_count(db_session, user.id) == 1

    change = _change_password(client, token)
    assert change.status_code == 200
    payload = change.get_json()
    assert set(payload.keys()) == {"message", "token", "password_changed_at"}
    assert payload["message"] == "Password changed successfully"
    assert payload["token"]
    assert payload["password_changed_at"]

    assert _email_change_request_count(db_session, user.id) == 0

    for raw in (old_raw, new_raw):
        verify = _verify_email_change(client, raw)
        assert verify.status_code == 400
        assert verify.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}

    db_session.refresh(user)
    assert user.email == original_email


def test_password_change_invalidates_partially_confirmed_email_change(
    client, db_session
) -> None:
    user, token = _auth_client_for(client, db_session)
    original_email = user.email

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, new_raw = _email_change_tokens_from_send_mock(mock_send)

    first = _verify_email_change(client, old_raw)
    assert first.status_code == 200
    assert first.get_json()["email_change_complete"] is False
    assert _email_change_request_count(db_session, user.id) == 1

    change = _change_password(client, token)
    assert change.status_code == 200
    assert _email_change_request_count(db_session, user.id) == 0

    remaining = _verify_email_change(client, new_raw)
    assert remaining.status_code == 400
    assert remaining.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}

    # Previously confirmed token must also be unusable.
    replay = _verify_email_change(client, old_raw)
    assert replay.status_code == 400
    assert replay.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}

    db_session.refresh(user)
    assert user.email == original_email


def test_password_change_does_not_invalidate_other_users_email_change(
    client, db_session
) -> None:
    user_a, token_a = _auth_client_for(
        client,
        db_session,
        email="usera@example.com",
    )
    user_b, token_b = _auth_client_for(
        client,
        db_session,
        email="userb@example.com",
    )

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(
            client, token_a, new_email="usera-new@example.com"
        ).status_code == 200
        old_a, new_a = _email_change_tokens_from_send_mock(mock_send)

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(
            client, token_b, new_email="userb-new@example.com"
        ).status_code == 200
        old_b, new_b = _email_change_tokens_from_send_mock(mock_send)

    change = _change_password(client, token_a)
    assert change.status_code == 200

    assert _email_change_request_count(db_session, user_a.id) == 0
    assert _email_change_request_count(db_session, user_b.id) == 1

    for raw in (old_a, new_a):
        verify = _verify_email_change(client, raw)
        assert verify.status_code == 400
        assert verify.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}

    first_b = _verify_email_change(client, old_b)
    assert first_b.status_code == 200
    assert first_b.get_json()["email_change_complete"] is False
    second_b = _verify_email_change(client, new_b)
    assert second_b.status_code == 200
    assert second_b.get_json()["email_change_complete"] is True
    db_session.refresh(user_b)
    assert user_b.email == "userb-new@example.com"
    db_session.refresh(user_a)
    assert user_a.email == "usera@example.com"


def test_new_email_change_request_works_after_password_change(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token, new_email="stale@example.com").status_code == 200
        stale_old, stale_new = _email_change_tokens_from_send_mock(mock_send)

    change = _change_password(client, token)
    assert change.status_code == 200
    replacement = change.get_json()["token"]
    assert _email_change_request_count(db_session, user.id) == 0

    for raw in (stale_old, stale_new):
        verify = _verify_email_change(client, raw)
        assert verify.status_code == 400
        assert verify.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert (
            _change_email(
                client,
                replacement,
                new_email=NEW_EMAIL,
                current_password=NEW_PASSWORD,
            ).status_code
            == 200
        )
        old_raw, new_raw = _email_change_tokens_from_send_mock(mock_send)

    assert _email_change_request_count(db_session, user.id) == 1
    first = _verify_email_change(client, old_raw)
    assert first.status_code == 200
    assert first.get_json()["email_change_complete"] is False
    second = _verify_email_change(client, new_raw)
    assert second.status_code == 200
    assert second.get_json()["email_change_complete"] is True
    db_session.refresh(user)
    assert user.email == NEW_EMAIL


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
