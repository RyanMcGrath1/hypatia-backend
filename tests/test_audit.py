"""Central audit service and security-logging tests."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import func, select

from hypatia.models import AccountEvent, Session
from hypatia.models.account_event import REQUEST_ID_MAX_LENGTH, USER_AGENT_MAX_LENGTH
from hypatia.services.audit import (
    get_audit_request_context,
    log_security_event,
    record_account_event,
)
from hypatia.services.auth.authentication import authenticate_user
from hypatia.services.auth.constants import (
    EVENT_ACCOUNT_CREATED,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGOUT,
    EVENT_PASSWORD_CHANGED,
    INVALID_CREDENTIALS_MESSAGE,
)
from hypatia.services.auth.sessions import create_session, logout_session
from tests.auth_helpers import auth_headers, create_user, login


def test_record_account_event_populates_fields_without_commit(db_session) -> None:
    user = create_user(db_session, email="audit@example.com", password="validpassword12")

    event = record_account_event(
        user,
        EVENT_PASSWORD_CHANGED,
        ip_address="203.0.113.50",
        request_id="req-correlation-1",
        user_agent="HypatiaTest/1.0",
    )

    assert event.user_id == user.id
    assert event.event_type == EVENT_PASSWORD_CHANGED
    assert event.ip_address == "203.0.113.50"
    assert event.request_id == "req-correlation-1"
    assert event.user_agent == "HypatiaTest/1.0"
    assert event.created_at is not None
    assert isinstance(event.created_at, datetime)

    # Helper must not commit independently: rollback drops the pending event.
    db_session.rollback()
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AccountEvent)
            .where(AccountEvent.user_id == user.id)
        )
        == 0
    )


def test_record_account_event_persists_with_parent_commit(db_session) -> None:
    user = create_user(db_session, email="audit2@example.com", password="validpassword12")

    record_account_event(
        user,
        EVENT_ACCOUNT_CREATED,
        ip_address="198.51.100.9",
        request_id="req-ok",
        user_agent="Agent/2",
    )
    db_session.commit()

    events = db_session.scalars(
        select(AccountEvent).where(AccountEvent.user_id == user.id)
    ).all()
    assert len(events) == 1
    assert events[0].event_type == EVENT_ACCOUNT_CREATED
    assert events[0].request_id == "req-ok"
    assert events[0].user_agent == "Agent/2"


def test_record_account_event_rolls_back_with_parent(db_session) -> None:
    user = create_user(db_session, email="audit3@example.com", password="validpassword12")
    before = db_session.scalar(select(func.count()).select_from(AccountEvent))

    record_account_event(user, EVENT_LOGIN_SUCCESS, ip_address="127.0.0.1")
    db_session.rollback()

    assert db_session.scalar(select(func.count()).select_from(AccountEvent)) == before


def test_user_agent_missing_and_oversized_are_handled(db_session) -> None:
    user = create_user(db_session, email="ua@example.com", password="validpassword12")

    missing = record_account_event(user, EVENT_LOGOUT, user_agent=None)
    empty = record_account_event(user, EVENT_LOGOUT, user_agent="")
    oversized = "x" * (USER_AGENT_MAX_LENGTH + 40)
    truncated = record_account_event(user, EVENT_LOGOUT, user_agent=oversized)
    db_session.commit()

    assert missing.user_agent is None
    assert empty.user_agent is None
    assert truncated.user_agent is not None
    assert len(truncated.user_agent) == USER_AGENT_MAX_LENGTH


def test_request_id_oversized_is_truncated(db_session) -> None:
    user = create_user(db_session, email="rid@example.com", password="validpassword12")
    oversized = "r" * (REQUEST_ID_MAX_LENGTH + 20)
    event = record_account_event(user, EVENT_LOGOUT, request_id=oversized)
    db_session.commit()
    assert event.request_id is not None
    assert len(event.request_id) == REQUEST_ID_MAX_LENGTH


def test_audit_rows_do_not_contain_sensitive_values(db_session) -> None:
    password = "super-secret-password"
    user = create_user(db_session, email="safe@example.com", password=password)
    raw_token, _session = create_session(user)
    db_session.commit()

    record_account_event(
        user,
        EVENT_LOGIN_SUCCESS,
        ip_address="203.0.113.1",
        request_id="safe-req",
        user_agent="SafeAgent/1",
    )
    db_session.commit()

    event = db_session.scalar(select(AccountEvent).where(AccountEvent.user_id == user.id))
    assert event is not None
    blob = " ".join(
        [
            str(event.event_type),
            str(event.ip_address),
            str(event.request_id),
            str(event.user_agent),
            str(event.user_id),
        ]
    )
    assert password not in blob
    assert user.password_hash not in blob
    assert raw_token not in blob
    assert "Authorization" not in blob
    assert "Bearer" not in blob


def test_unknown_email_login_security_log_excludes_secrets(caplog, db_session) -> None:
    attempted_email = "missing-user@example.com"
    attempted_password = "attempted-password-99"

    with caplog.at_level(logging.INFO, logger="hypatia.security"):
        result = authenticate_user(
            attempted_email,
            attempted_password,
            ip_address="203.0.113.77",
            request_id="unknown-login-req",
        )

    assert result.success is False
    assert db_session.scalar(select(func.count()).select_from(AccountEvent)) == 0

    security_records = [
        r for r in caplog.records if r.name == "hypatia.security" and getattr(r, "event", None) == "security_event"
    ]
    assert len(security_records) == 1
    record = security_records[0]
    assert record.event_type == EVENT_LOGIN_FAILED
    assert getattr(record, "request_id", None) == "unknown-login-req"
    assert getattr(record, "ip_address", None) == "203.0.113.77"
    assert not hasattr(record, "user_id") or getattr(record, "user_id", None) in (None, "")

    combined = " ".join(
        [
            record.getMessage(),
            str(getattr(record, "event_type", "")),
            str(getattr(record, "request_id", "")),
            str(getattr(record, "ip_address", "")),
            str(getattr(record, "user_id", "")),
        ]
    )
    assert attempted_email not in combined
    assert attempted_password not in combined


def test_unknown_email_login_http_stays_generic(client, db_session, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="hypatia.security"):
        response = client.post(
            "/api/auth/login",
            data=json.dumps(
                {
                    "email": "nobody@example.com",
                    "password": "not-a-real-password",
                }
            ),
            content_type="application/json",
            headers={"X-Request-ID": "http-unknown-login"},
        )

    assert response.status_code == 401
    assert response.get_json() == {"error": INVALID_CREDENTIALS_MESSAGE}
    assert db_session.scalar(select(func.count()).select_from(AccountEvent)) == 0

    security_records = [
        r for r in caplog.records if r.name == "hypatia.security" and getattr(r, "event", None) == "security_event"
    ]
    assert len(security_records) >= 1
    messages = " ".join(r.getMessage() for r in security_records)
    assert "nobody@example.com" not in messages
    assert "not-a-real-password" not in messages


def test_logout_creates_logout_event_with_metadata(client, db_session) -> None:
    user = create_user(db_session, email="logout@example.com", password="validpassword12")
    token = login(client, email="logout@example.com", password="validpassword12")
    request_id = "logout-correlation-id"

    response = client.post(
        "/api/auth/logout",
        headers={
            **auth_headers(token),
            "X-Request-ID": request_id,
            "User-Agent": "LogoutAgent/9",
        },
    )
    assert response.status_code == 200

    events = db_session.scalars(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGOUT,
        )
    ).all()
    assert len(events) == 1
    assert events[0].request_id == request_id
    assert events[0].user_agent == "LogoutAgent/9"
    assert events[0].ip_address is not None

    session = db_session.scalar(select(Session).where(Session.user_id == user.id))
    assert session is not None
    assert session.revoked_at is not None


def test_unauthenticated_logout_creates_no_logout_event(client, db_session) -> None:
    before = db_session.scalar(
        select(func.count())
        .select_from(AccountEvent)
        .where(AccountEvent.event_type == EVENT_LOGOUT)
    )

    response = client.post("/api/auth/logout")
    assert response.status_code == 401

    after = db_session.scalar(
        select(func.count())
        .select_from(AccountEvent)
        .where(AccountEvent.event_type == EVENT_LOGOUT)
    )
    assert after == before


def test_authenticated_operation_request_id_correlates(client, db_session) -> None:
    user = create_user(db_session, email="corr@example.com", password="validpassword12")
    request_id = "correlate-me-please"

    response = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "corr@example.com", "password": "validpassword12"}),
        content_type="application/json",
        headers={"X-Request-ID": request_id, "User-Agent": "CorrAgent/1"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == request_id

    event = db_session.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == user.id,
            AccountEvent.event_type == EVENT_LOGIN_SUCCESS,
        )
    )
    assert event is not None
    assert event.request_id == request_id
    assert event.user_agent == "CorrAgent/1"


def test_get_audit_request_context_outside_request(app) -> None:
    with app.app_context():
        ctx = get_audit_request_context()
        assert ctx.ip_address is None
        assert ctx.request_id is None
        assert ctx.user_agent is None


def test_log_security_event_structured_fields(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="hypatia.security"):
        log_security_event(
            EVENT_LOGIN_FAILED,
            ip_address="192.0.2.10",
            request_id="sec-1",
        )

    records = [r for r in caplog.records if getattr(r, "event", None) == "security_event"]
    assert len(records) == 1
    assert records[0].event_type == EVENT_LOGIN_FAILED
    assert records[0].request_id == "sec-1"
    assert records[0].ip_address == "192.0.2.10"


def test_logout_session_helper_does_not_commit(db_session) -> None:
    user = create_user(db_session, email="helper-logout@example.com", password="validpassword12")
    raw_token, session = create_session(user)
    db_session.commit()

    logout_session(user, session, ip_address="127.0.0.1", request_id="x", user_agent="y")
    assert session.revoked_at is not None

    # Helper must not commit: rolling back undoes revoke + LOGOUT together.
    db_session.rollback()
    db_session.refresh(session)
    assert session.revoked_at is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AccountEvent)
            .where(AccountEvent.event_type == EVENT_LOGOUT)
        )
        == 0
    )
    assert raw_token  # retain token only to assert we never logged it above
