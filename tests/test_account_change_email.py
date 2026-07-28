"""POST /api/account/change-email and /verify tests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select

from hypatia.models import AccountEvent, EmailChangeRequest, Session, User
from hypatia.services.account import (
    CURRENT_PASSWORD_INCORRECT_MESSAGE,
    EMAIL_CHANGE_COMPLETE_MESSAGE,
    EMAIL_CHANGE_CONFIRMATION_MESSAGE,
    EMAIL_DELIVERY_FAILED_MESSAGE,
    INVALID_VERIFICATION_TOKEN_MESSAGE,
    NEW_EMAIL_SAME_AS_CURRENT_MESSAGE,
    hash_email_change_token,
)
from hypatia.services.auth.constants import (
    EMAIL_ALREADY_REGISTERED_MESSAGE,
    EVENT_EMAIL_CHANGE_REQUESTED,
    EVENT_EMAIL_CHANGED,
    UNAUTHENTICATED_MESSAGE,
)
from hypatia.services.auth.sessions import create_session, revoke_session
from hypatia.services.email import EmailDeliveryError
from tests.auth_helpers import auth_headers, create_user_with_profile, login

PASSWORD = "validpassword12"
NEW_EMAIL = "new@example.com"
VERIFY_URL_BASE = "hypatia://verify-email-change"

_TOKEN_RE = re.compile(r"token=([^\s&]+)")


def _auth_client_for(client, db_session, **user_kwargs):
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


def _change_email(client, token: str, *, new_email: str = NEW_EMAIL, current_password: str = PASSWORD):
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


def _verify(client, raw_token: str):
    return client.post(
        "/api/account/change-email/verify",
        data=json.dumps({"token": raw_token}),
        content_type="application/json",
    )


def _extract_token(text: str) -> str:
    match = _TOKEN_RE.search(text)
    assert match is not None, f"token not found in email body: {text!r}"
    return match.group(1)


def _tokens_from_send_mock(mock_send) -> tuple[str, str, list]:
    """Return (old_raw_token, new_raw_token, call list) from send_email mock."""
    calls = mock_send.call_args_list
    assert len(calls) >= 2
    old_body = calls[0].kwargs["text_body"]
    new_body = calls[1].kwargs["text_body"]
    return _extract_token(old_body), _extract_token(new_body), calls


def _pending_for(db_session, user_id) -> EmailChangeRequest | None:
    return db_session.scalar(
        select(EmailChangeRequest).where(
            EmailChangeRequest.user_id == user_id,
            EmailChangeRequest.completed_at.is_(None),
        )
    )


def _event_count(db_session, *, user_id, event_type: str) -> int:
    return db_session.scalar(
        select(func.count())
        .select_from(AccountEvent)
        .where(
            AccountEvent.user_id == user_id,
            AccountEvent.event_type == event_type,
        )
    )


# --- Authentication ---


def test_change_email_without_auth_returns_401(client) -> None:
    response = client.post(
        "/api/account/change-email",
        data=json.dumps({"new_email": NEW_EMAIL, "current_password": PASSWORD}),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


def test_change_email_with_revoked_session_returns_401(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    session_row = db_session.scalars(select(Session).where(Session.user_id == user.id)).one()
    revoke_session(session_row)
    db_session.commit()

    response = _change_email(client, token)
    assert response.status_code == 401
    assert response.get_json() == {"error": UNAUTHENTICATED_MESSAGE}


# --- Current password ---


def test_correct_password_allows_request(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        response = _change_email(client, token)
    assert response.status_code == 200
    assert _pending_for(db_session, user.id) is not None
    assert mock_send.call_count == 2


def test_incorrect_password_returns_400_and_sends_nothing(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        response = _change_email(client, token, current_password="wrongpassword!!!!!")
    assert response.status_code == 400
    assert response.get_json() == {"error": CURRENT_PASSWORD_INCORRECT_MESSAGE}
    assert _pending_for(db_session, user.id) is None
    assert mock_send.call_count == 0
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGE_REQUESTED) == 0


# --- New email validation ---


def test_valid_normalized_email_accepted(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email"):
        response = _change_email(client, token, new_email="  New.Address@Example.COM ")
    assert response.status_code == 200
    pending = _pending_for(db_session, user.id)
    assert pending is not None
    assert pending.new_email == "new.address@example.com"
    assert pending.old_email == user.email


def test_invalid_email_rejected(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        response = _change_email(client, token, new_email="not-an-email")
    assert response.status_code == 400
    assert "email" in response.get_json()["error"].casefold()
    assert _pending_for(db_session, user.id) is None
    assert mock_send.call_count == 0


def test_same_as_current_email_rejected(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session, email="Same@Example.com")
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        response = _change_email(client, token, new_email=" same@example.com ")
    assert response.status_code == 400
    assert response.get_json() == {"error": NEW_EMAIL_SAME_AS_CURRENT_MESSAGE}
    assert _pending_for(db_session, user.id) is None
    assert mock_send.call_count == 0


def test_already_used_email_rejected(client, db_session) -> None:
    create_user_with_profile(
        db_session,
        email="taken@example.com",
        password=PASSWORD,
        first_name="Other",
        last_name="User",
    )
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        response = _change_email(client, token, new_email="taken@example.com")
    assert response.status_code == 409
    assert response.get_json() == {"error": EMAIL_ALREADY_REGISTERED_MESSAGE}
    assert _pending_for(db_session, user.id) is None
    assert mock_send.call_count == 0


# --- Request creation ---


def test_pending_request_stores_hashes_not_raw_tokens(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        response = _change_email(client, token)
    assert response.status_code == 200

    old_raw, new_raw, _ = _tokens_from_send_mock(mock_send)
    assert old_raw != new_raw

    pending = _pending_for(db_session, user.id)
    assert pending is not None
    assert pending.old_email == "user@example.com"
    assert pending.new_email == NEW_EMAIL
    assert pending.old_email_token_hash == hash_email_change_token(old_raw)
    assert pending.new_email_token_hash == hash_email_change_token(new_raw)
    assert len(pending.old_email_token_hash) == 64
    assert len(pending.new_email_token_hash) == 64

    # Raw tokens must not appear anywhere in persisted request fields.
    serialized = (
        f"{pending.old_email}|{pending.new_email}|"
        f"{pending.old_email_token_hash}|{pending.new_email_token_hash}"
    )
    assert old_raw not in serialized
    assert new_raw not in serialized

    # API must not return token hashes.
    payload = response.get_json()
    assert "token" not in payload
    assert "hash" not in json.dumps(payload).casefold()

    assert pending.expires_at is not None
    assert pending.created_at is not None
    created = pending.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    expires = pending.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = expires - created
    assert timedelta(hours=7, minutes=50) <= delta <= timedelta(hours=8, minutes=10)


def test_prior_pending_request_is_removed(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email"):
        assert _change_email(client, token, new_email="first@example.com").status_code == 200
        first_id = _pending_for(db_session, user.id).id
        assert _change_email(client, token, new_email="second@example.com").status_code == 200

    pending = _pending_for(db_session, user.id)
    assert pending is not None
    assert pending.id != first_id
    assert pending.new_email == "second@example.com"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EmailChangeRequest)
            .where(EmailChangeRequest.user_id == user.id)
        )
        == 1
    )


# --- Email delivery ---


def test_confirmation_emails_contain_only_their_own_tokens(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200

    old_raw, new_raw, calls = _tokens_from_send_mock(mock_send)
    assert calls[0].kwargs["to_address"] == user.email
    assert calls[1].kwargs["to_address"] == NEW_EMAIL

    old_body = calls[0].kwargs["text_body"]
    new_body = calls[1].kwargs["text_body"]
    assert old_raw in old_body
    assert new_raw not in old_body
    assert new_raw in new_body
    assert old_raw not in new_body
    assert PASSWORD not in old_body and PASSWORD not in new_body
    assert user.password_hash not in old_body and user.password_hash not in new_body
    assert token not in old_body and token not in new_body

    old_link = next(line for line in old_body.splitlines() if "token=" in line)
    new_link = next(line for line in new_body.splitlines() if "token=" in line)
    assert old_link.startswith(VERIFY_URL_BASE)
    assert new_link.startswith(VERIFY_URL_BASE)
    assert parse_qs(urlsplit(old_link).query)["token"] == [old_raw]
    assert parse_qs(urlsplit(new_link).query)["token"] == [new_raw]
    assert NEW_EMAIL in old_body


def test_smtp_failure_cleans_up_pending_and_skips_event(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    def _fail_second(*args, **kwargs):
        if _fail_second.calls == 0:
            _fail_second.calls += 1
            return None
        raise EmailDeliveryError("SMTP down")

    _fail_second.calls = 0

    with patch(
        "hypatia.services.account.email_change.send_email",
        side_effect=_fail_second,
    ):
        response = _change_email(client, token)

    assert response.status_code == 503
    assert response.get_json() == {"error": EMAIL_DELIVERY_FAILED_MESSAGE}
    assert _pending_for(db_session, user.id) is None
    assert (
        db_session.scalar(select(func.count()).select_from(EmailChangeRequest)) == 0
    )
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGE_REQUESTED) == 0
    db_session.refresh(user)
    assert user.email == "user@example.com"


def test_successful_delivery_creates_exactly_one_requested_event(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email"):
        assert _change_email(client, token).status_code == 200
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGE_REQUESTED) == 1
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGED) == 0


# --- Verification ---


def test_nonexistent_token_rejected(client, db_session) -> None:
    response = _verify(client, "not-a-real-token-value-at-all")
    assert response.status_code == 400
    assert response.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}


def test_expired_token_rejected(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, _, _ = _tokens_from_send_mock(mock_send)

    pending = _pending_for(db_session, user.id)
    pending.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    response = _verify(client, old_raw)
    assert response.status_code == 400
    assert response.get_json() == {"error": INVALID_VERIFICATION_TOKEN_MESSAGE}
    db_session.refresh(user)
    assert user.email == "user@example.com"


def test_current_email_token_confirms_current_side_only(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, new_raw, _ = _tokens_from_send_mock(mock_send)

    response = _verify(client, old_raw)
    assert response.status_code == 200
    assert response.get_json() == {
        "message": EMAIL_CHANGE_CONFIRMATION_MESSAGE,
        "email_change_complete": False,
    }

    pending = _pending_for(db_session, user.id)
    assert pending.old_email_confirmed_at is not None
    assert pending.new_email_confirmed_at is None
    db_session.refresh(user)
    assert user.email == "user@example.com"
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGED) == 0

    # Repeated current-side token has no duplicate side effects.
    again = _verify(client, old_raw)
    assert again.status_code == 200
    assert again.get_json()["email_change_complete"] is False
    db_session.refresh(pending)
    first_confirmed = pending.old_email_confirmed_at
    assert pending.new_email_confirmed_at is None
    # Still only waiting; new token unused.
    assert hash_email_change_token(new_raw) == pending.new_email_token_hash
    assert first_confirmed is not None


def test_new_email_token_confirms_new_side_only(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        _, new_raw, _ = _tokens_from_send_mock(mock_send)

    response = _verify(client, new_raw)
    assert response.status_code == 200
    assert response.get_json()["email_change_complete"] is False

    pending = _pending_for(db_session, user.id)
    assert pending.new_email_confirmed_at is not None
    assert pending.old_email_confirmed_at is None
    db_session.refresh(user)
    assert user.email == "user@example.com"


# --- Completion ---


def test_both_confirmations_change_email_and_revoke_sessions(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    # Extra session that must also be revoked.
    extra_raw, _ = create_session(user)
    db_session.commit()

    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, new_raw, _ = _tokens_from_send_mock(mock_send)
        assert mock_send.call_count == 2

        assert _verify(client, old_raw).status_code == 200
        complete = _verify(client, new_raw)

    assert complete.status_code == 200
    assert complete.get_json() == {
        "message": EMAIL_CHANGE_COMPLETE_MESSAGE,
        "email_change_complete": True,
    }

    db_session.refresh(user)
    assert user.email == NEW_EMAIL
    assert user.email_verified is True
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGED) == 1

    completed = db_session.scalars(
        select(EmailChangeRequest).where(EmailChangeRequest.user_id == user.id)
    ).one()
    assert completed.completed_at is not None
    assert _pending_for(db_session, user.id) is None

    # All sessions revoked; old bearer tokens rejected.
    sessions = db_session.scalars(select(Session).where(Session.user_id == user.id)).all()
    assert sessions
    assert all(s.revoked_at is not None for s in sessions)

    profile = client.get("/api/profile", headers=auth_headers(token))
    assert profile.status_code == 401
    assert client.get("/api/profile", headers=auth_headers(extra_raw)).status_code == 401

    # Old email login fails; new email + same password succeeds.
    old_login = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "user@example.com", "password": PASSWORD}),
        content_type="application/json",
    )
    assert old_login.status_code == 401

    new_token = login(client, email=NEW_EMAIL, password=PASSWORD)
    assert client.get("/api/profile", headers=auth_headers(new_token)).status_code == 200

    # Final notification to old address after completion (third send_email call).
    assert mock_send.call_count == 3
    notify = mock_send.call_args_list[2]
    assert notify.kwargs["to_address"] == "user@example.com"
    assert "changed" in notify.kwargs["text_body"].casefold()
    # Confirmation tokens must not appear in the final notification.
    assert old_raw not in notify.kwargs["text_body"]
    assert new_raw not in notify.kwargs["text_body"]


def test_uniqueness_rechecked_at_completion(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)
    with patch("hypatia.services.account.email_change.send_email") as mock_send:
        assert _change_email(client, token, new_email="race@example.com").status_code == 200
        old_raw, new_raw, _ = _tokens_from_send_mock(mock_send)
        assert _verify(client, old_raw).status_code == 200

        # Another account claims the proposed email while waiting.
        create_user_with_profile(
            db_session,
            email="race@example.com",
            password=PASSWORD,
            first_name="Race",
            last_name="Condition",
        )

        response = _verify(client, new_raw)

    assert response.status_code == 409
    assert response.get_json() == {"error": EMAIL_ALREADY_REGISTERED_MESSAGE}
    db_session.refresh(user)
    assert user.email == "user@example.com"
    assert user.email_verified is False
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGED) == 0
    assert _pending_for(db_session, user.id) is None


def test_post_change_notification_failure_does_not_undo_change(client, db_session) -> None:
    user, token = _auth_client_for(client, db_session)

    def _send_side_effect(*args, **kwargs):
        _send_side_effect.calls += 1
        # First two are confirmations; third is post-change notification.
        if _send_side_effect.calls <= 2:
            return None
        raise EmailDeliveryError("notify failed")

    _send_side_effect.calls = 0

    with patch(
        "hypatia.services.account.email_change.send_email",
        side_effect=_send_side_effect,
    ) as mock_send:
        assert _change_email(client, token).status_code == 200
        old_raw, new_raw, _ = _tokens_from_send_mock(mock_send)
        assert _verify(client, old_raw).status_code == 200
        complete = _verify(client, new_raw)

    assert complete.status_code == 200
    assert complete.get_json()["email_change_complete"] is True
    db_session.refresh(user)
    assert user.email == NEW_EMAIL
    assert user.email_verified is True
    assert _event_count(db_session, user_id=user.id, event_type=EVENT_EMAIL_CHANGED) == 1


def test_verify_missing_token_field_returns_400(client) -> None:
    response = client.post(
        "/api/account/change-email/verify",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "token is required"}
