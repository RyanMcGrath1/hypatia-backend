"""Authentication rate-limiting regression tests (Security Finding #2B)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pyotp
from sqlalchemy import func, select

from hypatia.extensions import limiter
from hypatia.models import MfaLoginChallenge, Session
from hypatia.services.auth.constants import INVALID_CREDENTIALS_MESSAGE
from hypatia.services.auth.mfa_challenge import hash_mfa_challenge_token
from hypatia.services.auth.rate_limit import AUTH_RATE_LIMITED_MESSAGE
from hypatia.services.auth.sessions import validate_session
from tests.auth_helpers import auth_headers, create_user, create_user_with_profile, login

PASSWORD = "validpassword12"
RATE_LIMITED_BODY = {"error": AUTH_RATE_LIMITED_MESSAGE}


def _configure_limits(
    app,
    *,
    login_account: int = 1000,
    login_ip: int = 1000,
    totp_account: int = 1000,
    totp_ip: int = 1000,
    window_minutes: int = 15,
) -> None:
    app.config["AUTH_LOGIN_ACCOUNT_LIMIT"] = login_account
    app.config["AUTH_LOGIN_ACCOUNT_WINDOW_MINUTES"] = window_minutes
    app.config["AUTH_LOGIN_IP_LIMIT"] = login_ip
    app.config["AUTH_LOGIN_IP_WINDOW_MINUTES"] = window_minutes
    app.config["AUTH_TOTP_ACCOUNT_LIMIT"] = totp_account
    app.config["AUTH_TOTP_ACCOUNT_WINDOW_MINUTES"] = window_minutes
    app.config["AUTH_TOTP_IP_LIMIT"] = totp_ip
    app.config["AUTH_TOTP_IP_WINDOW_MINUTES"] = window_minutes
    with app.app_context():
        limiter.reset()


def _post_login(client, *, email: str, password: str = PASSWORD, environ=None):
    kwargs = {
        "data": json.dumps({"email": email, "password": password}),
        "content_type": "application/json",
    }
    if environ is not None:
        kwargs["environ_base"] = environ
    return client.post("/api/auth/login", **kwargs)


def _post_totp(client, *, challenge_token: str, code: str, environ=None):
    kwargs = {
        "data": json.dumps({"challenge_token": challenge_token, "code": code}),
        "content_type": "application/json",
    }
    if environ is not None:
        kwargs["environ_base"] = environ
    return client.post("/api/auth/login/totp", **kwargs)


def _ip(addr: str) -> dict[str, str]:
    return {"REMOTE_ADDR": addr}


def _enroll_totp(client, db_session, *, email: str) -> tuple[object, str]:
    user = create_user_with_profile(
        db_session,
        email=email,
        password=PASSWORD,
        first_name="Rate",
        last_name="Limit",
    )
    token = login(client, email=email, password=PASSWORD)
    with patch("hypatia.services.security.totp.send_email"):
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
            data=json.dumps({"code": pyotp.TOTP(secret).now()}),
            content_type="application/json",
            headers=auth_headers(token),
        )
        assert enabled.status_code == 200
    db_session.refresh(user)
    return user, secret


def _assert_rate_limited(response) -> None:
    assert response.status_code == 429
    assert response.get_json() == RATE_LIMITED_BODY
    assert "Retry-After" in response.headers


# --- Login per-account ---


def test_login_per_account_limit_returns_429(app, client, db_session) -> None:
    _configure_limits(app, login_account=3, login_ip=1000)
    create_user(db_session, email="acct-limit@example.com", password=PASSWORD)

    for _ in range(3):
        resp = _post_login(client, email="acct-limit@example.com", password="wrong-password")
        assert resp.status_code == 401

    throttled = _post_login(client, email="acct-limit@example.com", password="wrong-password")
    _assert_rate_limited(throttled)
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0
    assert db_session.scalar(select(func.count()).select_from(MfaLoginChallenge)) == 0


def test_login_email_normalization_shares_account_bucket(app, client, db_session) -> None:
    _configure_limits(app, login_account=3, login_ip=1000)
    create_user(db_session, email="user@example.com", password=PASSWORD)

    assert (
        _post_login(client, email="User@Example.com", password="wrong").status_code == 401
    )
    assert (
        _post_login(client, email=" user@example.com ", password="wrong").status_code
        == 401
    )
    assert (
        _post_login(client, email="user@example.com", password="wrong").status_code == 401
    )

    throttled = _post_login(client, email="USER@EXAMPLE.COM", password="wrong")
    _assert_rate_limited(throttled)


def test_unknown_email_hits_account_rate_limit(app, client, db_session) -> None:
    _configure_limits(app, login_account=2, login_ip=1000)

    assert (
        _post_login(
            client, email="nobody-exists@example.com", password="whatever12ab"
        ).status_code
        == 401
    )
    assert (
        _post_login(
            client, email="nobody-exists@example.com", password="whatever12ab"
        ).status_code
        == 401
    )
    throttled = _post_login(
        client, email="nobody-exists@example.com", password="whatever12ab"
    )
    _assert_rate_limited(throttled)
    assert db_session.scalar(select(func.count()).select_from(Session)) == 0


# --- Login per-IP / isolation / account-across-IP ---


def test_login_per_ip_limit_across_emails(app, client, db_session) -> None:
    _configure_limits(app, login_account=1000, login_ip=3)
    create_user(db_session, email="a@example.com", password=PASSWORD)
    create_user(db_session, email="b@example.com", password=PASSWORD)
    create_user(db_session, email="c@example.com", password=PASSWORD)

    env = _ip("203.0.113.10")
    assert (
        _post_login(client, email="a@example.com", password="wrong", environ=env).status_code
        == 401
    )
    assert (
        _post_login(client, email="b@example.com", password="wrong", environ=env).status_code
        == 401
    )
    assert (
        _post_login(client, email="c@example.com", password="wrong", environ=env).status_code
        == 401
    )
    throttled = _post_login(
        client, email="d-never-created@example.com", password="wrong", environ=env
    )
    _assert_rate_limited(throttled)


def test_login_ip_limits_are_isolated(app, client, db_session) -> None:
    _configure_limits(app, login_account=1000, login_ip=2)
    create_user(db_session, email="iso@example.com", password=PASSWORD)

    env_a = _ip("198.51.100.1")
    env_b = _ip("198.51.100.2")

    assert (
        _post_login(client, email="iso@example.com", password="wrong", environ=env_a).status_code
        == 401
    )
    assert (
        _post_login(client, email="iso@example.com", password="wrong", environ=env_a).status_code
        == 401
    )
    _assert_rate_limited(
        _post_login(client, email="iso@example.com", password="wrong", environ=env_a)
    )

    # Different IP is not blocked solely because IP A is exhausted.
    create_user(db_session, email="iso-b@example.com", password=PASSWORD)
    ok = _post_login(
        client, email="iso-b@example.com", password="wrong", environ=env_b
    )
    assert ok.status_code == 401
    assert ok.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}


def test_login_account_limit_applies_across_ips(app, client, db_session) -> None:
    _configure_limits(app, login_account=3, login_ip=1000)
    create_user(db_session, email="cross-ip@example.com", password=PASSWORD)

    assert (
        _post_login(
            client,
            email="cross-ip@example.com",
            password="wrong",
            environ=_ip("203.0.113.1"),
        ).status_code
        == 401
    )
    assert (
        _post_login(
            client,
            email="cross-ip@example.com",
            password="wrong",
            environ=_ip("203.0.113.2"),
        ).status_code
        == 401
    )
    assert (
        _post_login(
            client,
            email="cross-ip@example.com",
            password="wrong",
            environ=_ip("203.0.113.3"),
        ).status_code
        == 401
    )
    throttled = _post_login(
        client,
        email="cross-ip@example.com",
        password="wrong",
        environ=_ip("203.0.113.4"),
    )
    _assert_rate_limited(throttled)


# --- MFA challenge must not mutate on 429 ---


def test_rate_limited_login_does_not_replace_mfa_challenge(app, client, db_session) -> None:
    _configure_limits(app, login_account=3, login_ip=1000)
    user, _secret = _enroll_totp(client, db_session, email="keep-challenge@example.com")
    with app.app_context():
        limiter.reset()

    first = _post_login(client, email="keep-challenge@example.com", password=PASSWORD)
    assert first.status_code == 200
    challenge_a = first.get_json()["challenge_token"]
    challenge_a_hash = hash_mfa_challenge_token(challenge_a)
    row_a = db_session.scalar(
        select(MfaLoginChallenge).where(MfaLoginChallenge.token_hash == challenge_a_hash)
    )
    assert row_a is not None
    attempt_count_before = row_a.attempt_count

    assert (
        _post_login(
            client, email="keep-challenge@example.com", password="wrong-password"
        ).status_code
        == 401
    )
    assert (
        _post_login(
            client, email="keep-challenge@example.com", password="wrong-password"
        ).status_code
        == 401
    )

    sessions_before = db_session.scalar(select(func.count()).select_from(Session))
    challenges_before = db_session.scalar(
        select(func.count())
        .select_from(MfaLoginChallenge)
        .where(MfaLoginChallenge.user_id == user.id)
    )

    throttled = _post_login(
        client, email="keep-challenge@example.com", password=PASSWORD
    )
    _assert_rate_limited(throttled)

    assert (
        db_session.scalar(
            select(MfaLoginChallenge).where(
                MfaLoginChallenge.token_hash == challenge_a_hash
            )
        )
        is not None
    )
    db_session.refresh(row_a)
    assert row_a.attempt_count == attempt_count_before
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        == challenges_before
    )
    assert db_session.scalar(select(func.count()).select_from(Session)) == sessions_before


def test_known_password_cannot_reset_challenge_budget_via_login(app, client, db_session) -> None:
    """Attacker with password cannot mint unlimited fresh MFA challenges."""
    _configure_limits(app, login_account=3, login_ip=1000)
    user, _secret = _enroll_totp(client, db_session, email="reset-attack@example.com")
    with app.app_context():
        limiter.reset()

    challenge_tokens: list[str] = []
    for _ in range(3):
        resp = _post_login(client, email="reset-attack@example.com", password=PASSWORD)
        assert resp.status_code == 200
        assert resp.get_json()["mfa_required"] is True
        challenge_tokens.append(resp.get_json()["challenge_token"])

    assert len(set(challenge_tokens)) == 3
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        == 1
    )
    final_hash = hash_mfa_challenge_token(challenge_tokens[-1])

    throttled = _post_login(client, email="reset-attack@example.com", password=PASSWORD)
    _assert_rate_limited(throttled)

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
            select(MfaLoginChallenge).where(MfaLoginChallenge.token_hash == final_hash)
        )
        is not None
    )


# --- TOTP limits ---


def test_totp_ip_rate_limit(app, client, db_session) -> None:
    app.config["TOTP_LOGIN_MAX_ATTEMPTS"] = 50
    _configure_limits(app, totp_ip=3, totp_account=1000, login_account=1000, login_ip=1000)
    user, secret = _enroll_totp(client, db_session, email="totp-ip@example.com")
    with app.app_context():
        limiter.reset()

    login_resp = _post_login(client, email="totp-ip@example.com", password=PASSWORD)
    challenge = login_resp.get_json()["challenge_token"]
    env = _ip("203.0.113.50")

    for _ in range(3):
        resp = _post_totp(client, challenge_token=challenge, code="000000", environ=env)
        assert resp.status_code == 401

    throttled = _post_totp(
        client, challenge_token=challenge, code="000000", environ=env
    )
    _assert_rate_limited(throttled)

    row = db_session.scalar(
        select(MfaLoginChallenge).where(
            MfaLoginChallenge.token_hash == hash_mfa_challenge_token(challenge)
        )
    )
    assert row is not None
    assert row.attempt_count == 3
    assert user.id == row.user_id
    assert secret


def test_totp_account_limit_survives_challenge_replacement(app, client, db_session) -> None:
    app.config["TOTP_LOGIN_MAX_ATTEMPTS"] = 50
    _configure_limits(app, totp_account=3, totp_ip=1000, login_account=1000, login_ip=1000)
    user, _secret = _enroll_totp(client, db_session, email="totp-acct@example.com")
    with app.app_context():
        limiter.reset()

    challenge_a = _post_login(
        client, email="totp-acct@example.com", password=PASSWORD
    ).get_json()["challenge_token"]

    for _ in range(2):
        assert (
            _post_totp(client, challenge_token=challenge_a, code="000000").status_code
            == 401
        )

    challenge_b = _post_login(
        client, email="totp-acct@example.com", password=PASSWORD
    ).get_json()["challenge_token"]
    assert challenge_a != challenge_b
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MfaLoginChallenge)
            .where(MfaLoginChallenge.user_id == user.id)
        )
        == 1
    )

    assert (
        _post_totp(client, challenge_token=challenge_b, code="000000").status_code == 401
    )
    throttled = _post_totp(client, challenge_token=challenge_b, code="000000")
    _assert_rate_limited(throttled)


# --- Normal auth still works; window recovery ---


def test_normal_login_and_totp_below_threshold(app, client, db_session) -> None:
    _configure_limits(app)
    create_user(db_session, email="plain@example.com", password=PASSWORD)
    user, secret = _enroll_totp(client, db_session, email="mfa@example.com")
    with app.app_context():
        limiter.reset()

    plain = _post_login(client, email="plain@example.com", password=PASSWORD)
    assert plain.status_code == 200
    payload = plain.get_json()
    assert payload["message"] == "Login successful"
    assert "token" in payload
    assert "Retry-After" not in plain.headers
    assert validate_session(payload["token"]).valid is True

    challenge_resp = _post_login(client, email="mfa@example.com", password=PASSWORD)
    assert challenge_resp.status_code == 200
    challenge_payload = challenge_resp.get_json()
    assert challenge_payload["mfa_required"] is True
    assert "token" not in challenge_payload
    assert "Retry-After" not in challenge_resp.headers

    method_last = user.totp_method.last_used_timecode
    if method_last is not None:
        next_time = (method_last + 1) * 30 + 1
        code = pyotp.TOTP(secret).at(next_time)
        with patch(
            "hypatia.services.security.totp_verify.time.time",
            return_value=float(next_time),
        ):
            complete = _post_totp(
                client,
                challenge_token=challenge_payload["challenge_token"],
                code=code,
            )
    else:
        complete = _post_totp(
            client,
            challenge_token=challenge_payload["challenge_token"],
            code=pyotp.TOTP(secret).now(),
        )
    assert complete.status_code == 200
    complete_payload = complete.get_json()
    assert complete_payload["message"] == "Login successful"
    assert "Retry-After" not in complete.headers
    assert validate_session(complete_payload["token"]).valid is True


def test_rate_limit_window_recovery_via_reset(app, client, db_session) -> None:
    """Recovery is verified via limiter.reset (supported test API).

    Full wall-clock window simulation is not used here to keep the suite fast;
    Flask-Limiter's in-memory counters clear through ``limiter.reset()``.
    """
    _configure_limits(app, login_account=1, login_ip=1000)
    create_user(db_session, email="recover@example.com", password=PASSWORD)

    assert (
        _post_login(client, email="recover@example.com", password="wrong").status_code
        == 401
    )
    _assert_rate_limited(
        _post_login(client, email="recover@example.com", password="wrong")
    )

    with app.app_context():
        limiter.reset()

    recovered = _post_login(client, email="recover@example.com", password="wrong")
    assert recovered.status_code == 401
    assert recovered.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}


def test_xff_header_does_not_spoof_login_ip_bucket(app, client, db_session) -> None:
    _configure_limits(app, login_account=1000, login_ip=2)
    create_user(db_session, email="xff@example.com", password=PASSWORD)

    env = _ip("203.0.113.77")
    headers = {"X-Forwarded-For": "198.51.100.99"}

    for _ in range(2):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"email": "xff@example.com", "password": "wrong"}),
            content_type="application/json",
            headers=headers,
            environ_base=env,
        )
        assert resp.status_code == 401

    throttled = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "xff@example.com", "password": "wrong"}),
        content_type="application/json",
        headers=headers,
        environ_base=env,
    )
    _assert_rate_limited(throttled)

    create_user(db_session, email="xff2@example.com", password=PASSWORD)
    other = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "xff2@example.com", "password": "wrong"}),
        content_type="application/json",
        headers=headers,
        environ_base=_ip("203.0.113.78"),
    )
    assert other.status_code == 401
