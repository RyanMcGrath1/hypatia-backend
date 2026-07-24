"""TOTP authenticator-app MFA tests."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pyotp
import pytest
from sqlalchemy import func, select

from hypatia.models import AccountEvent, MfaLoginChallenge, Session, TOTPMethod
from hypatia.services.auth.authentication import authenticate_user
from hypatia.services.auth.constants import (
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCESS,
    EVENT_TOTP_DISABLED,
    EVENT_TOTP_ENABLED,
    INVALID_CREDENTIALS_MESSAGE,
    UNAUTHENTICATED_MESSAGE,
)
from hypatia.services.auth.mfa_challenge import (
    create_mfa_login_challenge,
    hash_mfa_challenge_token,
)
from hypatia.services.auth.sessions import (
    create_session,
    hash_session_token,
    validate_session,
)
from hypatia.services.email import EmailDeliveryError
from hypatia.services.security.totp import (
    CURRENT_PASSWORD_INCORRECT_MESSAGE,
    TOTP_ALREADY_ENABLED_MESSAGE,
    TOTP_INVALID_CODE_MESSAGE,
    disable_totp,
    enable_totp,
    setup_totp,
)
from hypatia.services.security.totp_crypto import (
    TOTP_ENCRYPTION_INVALID_KEY_MESSAGE,
    TOTP_ENCRYPTION_NOT_CONFIGURED_MESSAGE,
    TotpEncryptionError,
    decrypt_totp_secret,
    encrypt_totp_secret,
)
from hypatia.services.security.totp_verify import (
    build_provisioning_uri,
    generate_totp_secret,
    verify_totp_code,
)
from tests.auth_helpers import auth_headers, create_user_with_profile, login

PASSWORD = "validpassword12"


def _auth_client(client, db_session, **user_kwargs):
    defaults = {
        "email": "user@example.com",
        "password": PASSWORD,
        "first_name": "Matthew",
        "last_name": "Thompson",
    }
    defaults.update(user_kwargs)
    user = create_user_with_profile(db_session, **defaults)
    token = login(client, email=defaults["email"], password=defaults["password"])
    return user, token


def _setup(client, token: str, *, current_password: str = PASSWORD):
    return client.post(
        "/api/security/totp/setup",
        data=json.dumps({"current_password": current_password}),
        content_type="application/json",
        headers=auth_headers(token),
    )


def _enable(client, token: str, code: str):
    return client.post(
        "/api/security/totp/enable",
        data=json.dumps({"code": code}),
        content_type="application/json",
        headers=auth_headers(token),
    )


def _disable(client, token: str, *, current_password: str, code: str):
    return client.post(
        "/api/security/totp/disable",
        data=json.dumps({"current_password": current_password, "code": code}),
        content_type="application/json",
        headers=auth_headers(token),
    )


def _current_code(secret: str, *, for_time: float | None = None) -> str:
    totp = pyotp.TOTP(secret, digits=6, interval=30)
    if for_time is None:
        return totp.now()
    return totp.at(for_time)


def _enroll_enabled(client, db_session, user, token: str) -> tuple[str, str]:
    """Setup + enable TOTP; return (plaintext_secret, new_session_token)."""
    setup = _setup(client, token)
    assert setup.status_code == 200
    secret = setup.get_json()["manual_entry_key"]
    enabled = _enable(client, token, _current_code(secret))
    assert enabled.status_code == 200
    db_session.refresh(user)
    return secret, enabled.get_json()["token"]


# --- Secret security ---


def test_generate_totp_secret_uses_pyotp(db_session) -> None:
    secret = generate_totp_secret()
    assert isinstance(secret, str)
    assert len(secret) >= 16
    # Base32 alphabet
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)


def test_plaintext_secret_not_stored(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    response = _setup(client, token)
    assert response.status_code == 200
    plaintext = response.get_json()["manual_entry_key"]

    method = db_session.get(TOTPMethod, user.id)
    assert method is not None
    assert method.secret_encrypted != plaintext
    assert plaintext not in method.secret_encrypted
    assert decrypt_totp_secret(method.secret_encrypted) == plaintext


def test_encrypt_decrypt_roundtrip(app, db_session) -> None:
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret)
    assert encrypted != secret
    assert decrypt_totp_secret(encrypted) == secret


def test_missing_encryption_key_fails_cleanly(app, db_session) -> None:
    app.config["TOTP_ENCRYPTION_KEY"] = ""
    with pytest.raises(TotpEncryptionError) as exc:
        encrypt_totp_secret("JBSWY3DPEHPK3PXP")
    assert str(exc.value) == TOTP_ENCRYPTION_NOT_CONFIGURED_MESSAGE


def test_invalid_encryption_key_fails_cleanly(app, db_session) -> None:
    app.config["TOTP_ENCRYPTION_KEY"] = "not-a-valid-fernet-key"
    with pytest.raises(TotpEncryptionError) as exc:
        encrypt_totp_secret("JBSWY3DPEHPK3PXP")
    assert str(exc.value) == TOTP_ENCRYPTION_INVALID_KEY_MESSAGE


def test_provisioning_uri_uses_issuer_and_email(client, db_session) -> None:
    user, token = _auth_client(client, db_session, email="ada@example.com")
    response = _setup(client, token)
    payload = response.get_json()
    uri = payload["provisioning_uri"]
    secret = payload["manual_entry_key"]

    assert uri.startswith("otpauth://totp/")
    assert "Hypatia" in uri
    assert "ada%40example.com" in uri or "ada@example.com" in uri
    assert build_provisioning_uri(
        secret_base32=secret,
        account_email="ada@example.com",
        issuer="Hypatia",
    ).startswith("otpauth://totp/")


def test_sensitive_totp_values_not_logged(client, db_session, caplog) -> None:
    user, token = _auth_client(client, db_session)
    with caplog.at_level(logging.DEBUG):
        response = _setup(client, token)
    payload = response.get_json()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert payload["manual_entry_key"] not in joined
    assert payload["provisioning_uri"] not in joined
    method = db_session.get(TOTPMethod, user.id)
    assert method is not None
    assert method.secret_encrypted not in joined


# --- Setup ---


def test_setup_requires_authentication(client, db_session) -> None:
    response = client.post(
        "/api/security/totp/setup",
        data=json.dumps({"current_password": PASSWORD}),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_setup_requires_current_password_field(client, db_session) -> None:
    _user, token = _auth_client(client, db_session)
    response = client.post(
        "/api/security/totp/setup",
        data=json.dumps({}),
        content_type="application/json",
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "current_password is required"


def test_setup_rejects_incorrect_password(client, db_session) -> None:
    _user, token = _auth_client(client, db_session)
    response = _setup(client, token, current_password="wrongpassword12")
    assert response.status_code == 400
    assert response.get_json()["error"] == CURRENT_PASSWORD_INCORRECT_MESSAGE


def test_setup_creates_disabled_method(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    response = _setup(client, token)
    assert response.status_code == 200
    payload = response.get_json()
    assert "provisioning_uri" in payload
    assert "manual_entry_key" in payload

    method = db_session.get(TOTPMethod, user.id)
    assert method is not None
    assert method.enabled is False
    assert method.verified_at is None


def test_repeated_incomplete_setup_replaces_secret(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    first = _setup(client, token).get_json()["manual_entry_key"]
    second = _setup(client, token).get_json()["manual_entry_key"]
    assert first != second
    assert db_session.scalar(select(func.count()).select_from(TOTPMethod)) == 1
    method = db_session.get(TOTPMethod, user.id)
    assert decrypt_totp_secret(method.secret_encrypted) == second


def test_setup_rejected_when_already_enabled(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_enabled(client, db_session, user, token)
    response = _setup(client, new_token)
    assert response.status_code == 400
    assert response.get_json()["error"] == TOTP_ALREADY_ENABLED_MESSAGE
    assert decrypt_totp_secret(user.totp_method.secret_encrypted) == secret


# --- Enable ---


def test_enable_valid_code(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret = _setup(client, token).get_json()["manual_entry_key"]
    response = _enable(client, token, _current_code(secret))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Authenticator app enabled"
    assert payload["totp_enabled"] is True
    assert payload["token"]

    db_session.refresh(user)
    assert user.totp_method.enabled is True
    assert user.totp_method.verified_at is not None
    assert user.totp_method.last_used_timecode is not None


def test_enable_invalid_code_does_not_enable(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _setup(client, token)
    response = _enable(client, token, "000000")
    assert response.status_code == 400
    assert response.get_json()["error"] == TOTP_INVALID_CODE_MESSAGE
    assert user.totp_method.enabled is False
    assert user.totp_method.verified_at is None


def test_enable_creates_exactly_one_totp_enabled_event(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret = _setup(client, token).get_json()["manual_entry_key"]
    _enable(client, token, _current_code(secret))

    events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_TOTP_ENABLED,
        )
    ).all()
    assert len(events) == 1


def test_enable_revokes_prior_sessions_and_returns_replacement(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    other_raw, _other = create_session(user)
    db_session.commit()

    secret = _setup(client, token).get_json()["manual_entry_key"]
    # Wait if needed so enable uses a different code than... enable is first use
    response = _enable(client, token, _current_code(secret))
    new_token = response.get_json()["token"]

    assert validate_session(token).valid is False
    assert validate_session(other_raw).valid is False
    assert validate_session(new_token).valid is True

    # Previous tokens rejected by protected route
    profile = client.get("/api/profile", headers=auth_headers(token))
    assert profile.status_code == 401


# --- Verify / replay ---


def test_verify_accepts_current_code_rejects_invalid() -> None:
    secret = generate_totp_secret()
    assert verify_totp_code(secret, _current_code(secret)).ok is True
    assert verify_totp_code(secret, "000000").ok is False


def test_verify_adjacent_window_accepted() -> None:
    secret = generate_totp_secret()
    now = time.time()
    prior = now - 30
    code = _current_code(secret, for_time=prior)
    result = verify_totp_code(secret, code, for_time=now, valid_window=1)
    assert result.ok is True
    assert result.matched_timecode == int(prior) // 30


def test_replay_prevention_rejects_consumed_timecode() -> None:
    secret = generate_totp_secret()
    first = verify_totp_code(secret, _current_code(secret))
    assert first.ok is True
    second = verify_totp_code(
        secret,
        _current_code(secret),
        last_used_timecode=first.matched_timecode,
    )
    assert second.ok is False


def test_last_used_timecode_updated_after_enable(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret = _setup(client, token).get_json()["manual_entry_key"]
    code = _current_code(secret)
    expected = verify_totp_code(secret, code)
    _enable(client, token, code)
    db_session.refresh(user)
    assert user.totp_method.last_used_timecode == expected.matched_timecode


# --- Login without TOTP ---


def test_password_only_login_unchanged(client, db_session) -> None:
    user = create_user_with_profile(
        db_session,
        email="plain@example.com",
        password=PASSWORD,
    )
    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "plain@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Login successful"
    assert "token" in payload
    assert "mfa_required" not in payload

    db_session.refresh(user)
    assert user.last_login_at is not None
    success_events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_SUCCESS,
        )
    ).all()
    assert len(success_events) == 1


# --- Login with TOTP ---


def test_password_phase_returns_challenge_not_session(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _secret, _new_token = _enroll_enabled(client, db_session, user, token)
    user.last_login_at = None
    db_session.commit()

    # Clear LOGIN_SUCCESS from earlier password-only login used to enroll
    for event in db_session.scalars(
        select(AccountEvent).where(AccountEvent.user_id == user.id)
    ).all():
        if event.event_type == EVENT_LOGIN_SUCCESS:
            db_session.delete(event)
    db_session.commit()

    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {
        "mfa_required": True,
        "mfa_method": "totp",
        "challenge_token": payload["challenge_token"],
    }
    assert "token" not in payload

    db_session.refresh(user)
    assert user.last_login_at is None
    success_events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_SUCCESS,
        )
    ).all()
    assert len(success_events) == 0

    raw_challenge = payload["challenge_token"]
    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(
                MfaLoginChallenge.token_hash == hash_mfa_challenge_token(raw_challenge)
            )
        )
        is not None
    )
    # Raw token not stored
    rows = db_session.scalars(select(MfaLoginChallenge)).all()
    for row in rows:
        assert raw_challenge not in (row.token_hash,)


def test_authenticate_user_defers_success_when_totp_enabled(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _enroll_enabled(client, db_session, user, token)
    user.last_login_at = None
    db_session.commit()

    result = authenticate_user("user@example.com", PASSWORD, commit=True)
    assert result.success is True
    assert result.mfa_required is True
    db_session.refresh(user)
    assert user.last_login_at is None


# --- MFA challenge completion ---


def test_valid_challenge_and_totp_returns_session(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, _ = _enroll_enabled(client, db_session, user, token)

    # Move past the enable-consumed timecode if still in same window
    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    challenge = login_resp.get_json()["challenge_token"]

    # Use a fresh code; if same window as enable, wait for next period
    method = db_session.get(TOTPMethod, user.id)
    code = _current_code(secret)
    verification = verify_totp_code(
        secret, code, last_used_timecode=method.last_used_timecode
    )
    if not verification.ok:
        # Advance into next window
        next_time = (method.last_used_timecode + 1) * 30 + 1
        with patch(
            "hypatia.services.security.totp_verify.time.time",
            return_value=float(next_time),
        ):
            code = _current_code(secret, for_time=next_time)
            complete = client.post(
                "/api/auth/login/totp",
                data=json.dumps({"challenge_token": challenge, "code": code}),
                content_type="application/json",
            )
    else:
        complete = client.post(
            "/api/auth/login/totp",
            data=json.dumps({"challenge_token": challenge, "code": code}),
            content_type="application/json",
        )

    assert complete.status_code == 200
    payload = complete.get_json()
    assert payload["message"] == "Login successful"
    assert validate_session(payload["token"]).valid is True

    db_session.refresh(user)
    assert user.last_login_at is not None
    success_events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_SUCCESS,
        )
    ).all()
    # One from enrollment login + one from MFA complete — enrollment used password login
    # before TOTP was enabled. After enable we cleared none here; count MFA completion:
    assert any(e.event_type == EVENT_LOGIN_SUCCESS for e in success_events)

    challenge_row = db_session.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge)
        )
    )
    assert challenge_row.consumed_at is not None


def test_nonexistent_expired_consumed_challenges_rejected(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, _ = _enroll_enabled(client, db_session, user, token)

    # nonexistent
    bad = client.post(
        "/api/auth/login/totp",
        data=json.dumps({"challenge_token": "nope", "code": "123456"}),
        content_type="application/json",
    )
    assert bad.status_code == 401
    assert bad.get_json()["error"] == INVALID_CREDENTIALS_MESSAGE

    # expired
    raw = create_mfa_login_challenge(user)
    challenge = db_session.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_mfa_challenge_token(raw)
        )
    )
    challenge.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    expired = client.post(
        "/api/auth/login/totp",
        data=json.dumps({"challenge_token": raw, "code": _current_code(secret)}),
        content_type="application/json",
    )
    assert expired.status_code == 401

    # consumed
    raw2 = create_mfa_login_challenge(user)
    challenge2 = db_session.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_mfa_challenge_token(raw2)
        )
    )
    challenge2.consumed_at = datetime.now(timezone.utc)
    db_session.commit()
    consumed = client.post(
        "/api/auth/login/totp",
        data=json.dumps({"challenge_token": raw2, "code": _current_code(secret)}),
        content_type="application/json",
    )
    assert consumed.status_code == 401


def test_inactive_user_challenge_rejected(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, _ = _enroll_enabled(client, db_session, user, token)
    raw = create_mfa_login_challenge(user)
    db_session.commit()
    user.account_status = "inactive"
    db_session.commit()

    response = client.post(
        "/api/auth/login/totp",
        data=json.dumps({"challenge_token": raw, "code": _current_code(secret)}),
        content_type="application/json",
    )
    assert response.status_code == 401


def test_challenge_token_cannot_be_used_as_session(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _enroll_enabled(client, db_session, user, token)
    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    challenge = login_resp.get_json()["challenge_token"]
    profile = client.get("/api/profile", headers=auth_headers(challenge))
    assert profile.status_code == 401
    assert validate_session(challenge).valid is False


def test_mfa_success_creates_exactly_one_login_success(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, _ = _enroll_enabled(client, db_session, user, token)

    # Remove prior LOGIN_SUCCESS events from enrollment path
    for event in list(
        db_session.scalars(
            select(AccountEvent).where(AccountEvent.user_id == user.id)
        ).all()
    ):
        if event.event_type == EVENT_LOGIN_SUCCESS:
            db_session.delete(event)
    user.last_login_at = None
    db_session.commit()

    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    challenge = login_resp.get_json()["challenge_token"]
    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        complete = client.post(
            "/api/auth/login/totp",
            data=json.dumps({"challenge_token": challenge, "code": code}),
            content_type="application/json",
        )
    assert complete.status_code == 200

    success_events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_SUCCESS,
        )
    ).all()
    assert len(success_events) == 1
    db_session.refresh(user)
    assert user.last_login_at is not None


# --- Attempt limit ---


def test_bad_totp_increments_attempts_and_records_login_failed(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    _enroll_enabled(client, db_session, user, token)
    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    challenge = login_resp.get_json()["challenge_token"]

    failed_before = db_session.scalar(
        select(func.count())
        .select_from(AccountEvent)
        .where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_FAILED,
        )
    )

    response = client.post(
        "/api/auth/login/totp",
        data=json.dumps({"challenge_token": challenge, "code": "000000"}),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == INVALID_CREDENTIALS_MESSAGE

    row = db_session.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge)
        )
    )
    assert row.attempt_count == 1
    failed_after = db_session.scalar(
        select(func.count())
        .select_from(AccountEvent)
        .where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_FAILED,
        )
    )
    assert failed_after == failed_before + 1


def test_challenge_exhausted_after_max_attempts(client, db_session, app) -> None:
    user, token = _auth_client(client, db_session)
    secret, _ = _enroll_enabled(client, db_session, user, token)
    app.config["TOTP_LOGIN_MAX_ATTEMPTS"] = 3

    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    challenge = login_resp.get_json()["challenge_token"]

    for _ in range(3):
        bad = client.post(
            "/api/auth/login/totp",
            data=json.dumps({"challenge_token": challenge, "code": "000000"}),
            content_type="application/json",
        )
        assert bad.status_code == 401

    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        exhausted = client.post(
            "/api/auth/login/totp",
            data=json.dumps({"challenge_token": challenge, "code": code}),
            content_type="application/json",
        )
    assert exhausted.status_code == 401


# --- Disable ---


def test_disable_requires_auth_password_and_code(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_enabled(client, db_session, user, token)

    unauth = client.post(
        "/api/security/totp/disable",
        data=json.dumps({"current_password": PASSWORD, "code": "123456"}),
        content_type="application/json",
    )
    assert unauth.status_code == 401

    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        password_only = _disable(client, new_token, current_password=PASSWORD, code="000000")
        assert password_only.status_code == 400

        wrong_password = _disable(
            client, new_token, current_password="wrongpassword12", code=code
        )
        assert wrong_password.status_code == 400
        assert wrong_password.get_json()["error"] == CURRENT_PASSWORD_INCORRECT_MESSAGE

        # TOTP-only (wrong password already covered); missing password field:
        missing_pw = client.post(
            "/api/security/totp/disable",
            data=json.dumps({"code": code}),
            content_type="application/json",
            headers=auth_headers(new_token),
        )
        assert missing_pw.status_code == 400


def test_disable_deletes_method_rotates_sessions_and_events(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_enabled(client, db_session, user, token)

    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch("hypatia.services.security.totp.send_email") as send_email:
            response = _disable(client, new_token, current_password=PASSWORD, code=code)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["message"] == "Authenticator app disabled"
    assert payload["totp_enabled"] is False
    replacement = payload["token"]

    assert db_session.get(TOTPMethod, user.id) is None
    assert validate_session(new_token).valid is False
    assert validate_session(replacement).valid is True

    disabled_events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_TOTP_DISABLED,
        )
    ).all()
    assert len(disabled_events) == 1

    # Future login no longer requires MFA
    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    assert "token" in login_resp.get_json()
    assert "mfa_required" not in login_resp.get_json()


# --- Profile ---


def test_profile_totp_enabled_flags(client, db_session) -> None:
    user, token = _auth_client(client, db_session)

    before = client.get("/api/profile", headers=auth_headers(token))
    assert before.get_json()["totp_enabled"] is False

    _setup(client, token)
    incomplete = client.get("/api/profile", headers=auth_headers(token))
    assert incomplete.get_json()["totp_enabled"] is False

    secret = decrypt_totp_secret(user.totp_method.secret_encrypted)
    enabled = _enable(client, token, _current_code(secret))
    new_token = enabled.get_json()["token"]
    after = client.get("/api/profile", headers=auth_headers(new_token))
    payload = after.get_json()
    assert payload["totp_enabled"] is True
    assert "secret_encrypted" not in payload
    assert "manual_entry_key" not in payload
    assert "provisioning_uri" not in payload
    assert "last_used_timecode" not in payload


# --- Email notifications ---


def test_enable_and_disable_send_notifications(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret = _setup(client, token).get_json()["manual_entry_key"]

    with patch("hypatia.services.security.totp.send_email") as send_email:
        enabled = _enable(client, token, _current_code(secret))
        assert enabled.status_code == 200
        assert send_email.call_count == 1
        kwargs = send_email.call_args.kwargs
        assert "enabled" in kwargs["text_body"].lower()
        assert secret not in kwargs["text_body"]
        assert enabled.get_json()["token"] not in kwargs["text_body"]
        assert "otpauth" not in kwargs["text_body"]

    new_token = enabled.get_json()["token"]
    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch("hypatia.services.security.totp.send_email") as send_email:
            disabled = _disable(client, new_token, current_password=PASSWORD, code=code)
            assert disabled.status_code == 200
            assert send_email.call_count == 1
            body = send_email.call_args.kwargs["text_body"]
            assert "disabled" in body.lower()
            assert secret not in body
            assert disabled.get_json()["token"] not in body


def test_notification_failure_does_not_undo_enable_or_disable(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret = _setup(client, token).get_json()["manual_entry_key"]

    with patch(
        "hypatia.services.security.totp.send_email",
        side_effect=EmailDeliveryError("smtp down"),
    ):
        enabled = _enable(client, token, _current_code(secret))
    assert enabled.status_code == 200
    db_session.refresh(user)
    assert user.totp_method.enabled is True

    new_token = enabled.get_json()["token"]
    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch(
            "hypatia.services.security.totp.send_email",
            side_effect=EmailDeliveryError("smtp down"),
        ):
            disabled = _disable(client, new_token, current_password=PASSWORD, code=code)
    assert disabled.status_code == 200
    assert db_session.get(TOTPMethod, user.id) is None


# --- Transaction safety ---


def test_failed_enable_session_rotation_rolls_back(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret = _setup(client, token).get_json()["manual_entry_key"]
    code = _current_code(secret)

    with patch(
        "hypatia.services.security.totp.create_session",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            enable_totp(
                user,
                db_session.scalar(
                    select(Session).where(
                        Session.token_hash == hash_session_token(token)
                    )
                ),
                code=code,
            )

    db_session.refresh(user)
    assert user.totp_method.enabled is False
    assert user.totp_method.verified_at is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AccountEvent)
            .where(
                AccountEvent.user_id == user.id,
                AccountEvent.event_type == EVENT_TOTP_ENABLED,
            )
        )
        == 0
    )


def test_failed_disable_session_rotation_rolls_back(client, db_session) -> None:
    user, token = _auth_client(client, db_session)
    secret, new_token = _enroll_enabled(client, db_session, user, token)
    session = db_session.scalar(
        select(Session).where(Session.token_hash == hash_session_token(new_token))
    )
    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1
    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch(
            "hypatia.services.security.totp.create_session",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                disable_totp(
                    user,
                    session,
                    current_password=PASSWORD,
                    code=code,
                )

    assert db_session.get(TOTPMethod, user.id) is not None
    assert db_session.get(TOTPMethod, user.id).enabled is True


def test_failed_complete_mfa_session_creation_does_not_mark_success(
    client, db_session
) -> None:
    user, token = _auth_client(client, db_session)
    secret, _ = _enroll_enabled(client, db_session, user, token)

    for event in list(
        db_session.scalars(
            select(AccountEvent).where(AccountEvent.user_id == user.id)
        ).all()
    ):
        if event.event_type == EVENT_LOGIN_SUCCESS:
            db_session.delete(event)
    user.last_login_at = None
    db_session.commit()

    login_resp = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    challenge = login_resp.get_json()["challenge_token"]
    method = db_session.get(TOTPMethod, user.id)
    next_time = (method.last_used_timecode + 1) * 30 + 1

    with patch(
        "hypatia.services.security.totp_verify.time.time",
        return_value=float(next_time),
    ):
        code = pyotp.TOTP(secret).at(next_time)
        with patch(
            "hypatia.services.auth.mfa_challenge.create_session",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                from hypatia.services.auth.mfa_challenge import complete_totp_login

                complete_totp_login(challenge_token=challenge, code=code)

    db_session.refresh(user)
    assert user.last_login_at is None
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
    challenge_row = db_session.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge)
        )
    )
    assert challenge_row.consumed_at is None
