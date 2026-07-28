"""Outbound SMTP email delivery tests (no external network)."""

from __future__ import annotations

import smtplib
from email.utils import parseaddr
from unittest.mock import MagicMock, patch

import pytest

from hypatia.services.email import (
    SMTP_SECURITY_NONE,
    SMTP_SECURITY_SSL,
    SMTP_SECURITY_STARTTLS,
    EmailDeliveryError,
    EmailNotConfiguredError,
    EmailSettings,
    build_message,
    load_email_settings,
    send_email,
)
from hypatia.utils.settings import Config


def _full_env(**overrides: str) -> dict[str, str]:
    base = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "mailer",
        "SMTP_PASSWORD": "secret-password",
        "SMTP_SECURITY": "starttls",
        "EMAIL_FROM_ADDRESS": "no-reply@example.com",
        "EMAIL_FROM_NAME": "Hypatia",
    }
    base.update(overrides)
    return base


def _settings(**overrides) -> EmailSettings:
    base = dict(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security=SMTP_SECURITY_STARTTLS,
        from_address="no-reply@example.com",
        from_name="Hypatia",
        smtp_username="mailer",
        smtp_password="secret-password",
        timeout_s=30.0,
    )
    base.update(overrides)
    return EmailSettings(**base)


# --- CONFIG ---


def test_config_exposes_email_env_keys() -> None:
    assert Config.ENV_SMTP_HOST == "SMTP_HOST"
    assert Config.ENV_SMTP_PORT == "SMTP_PORT"
    assert Config.ENV_SMTP_USERNAME == "SMTP_USERNAME"
    assert Config.ENV_SMTP_PASSWORD == "SMTP_PASSWORD"
    assert Config.ENV_SMTP_SECURITY == "SMTP_SECURITY"
    assert Config.ENV_EMAIL_FROM_ADDRESS == "EMAIL_FROM_ADDRESS"
    assert Config.ENV_EMAIL_FROM_NAME == "EMAIL_FROM_NAME"


def test_required_smtp_settings_are_read_correctly() -> None:
    settings = load_email_settings(_full_env())
    assert settings.smtp_host == "smtp.example.com"
    assert settings.smtp_port == 587
    assert settings.smtp_username == "mailer"
    assert settings.smtp_password == "secret-password"
    assert settings.smtp_security == SMTP_SECURITY_STARTTLS
    assert settings.from_address == "no-reply@example.com"
    assert settings.from_name == "Hypatia"


def test_invalid_smtp_security_is_rejected() -> None:
    with pytest.raises(ValueError, match="SMTP_SECURITY"):
        load_email_settings(_full_env(SMTP_SECURITY="tls"))


def test_missing_host_fails_with_email_not_configured() -> None:
    with pytest.raises(EmailNotConfiguredError) as exc_info:
        load_email_settings(_full_env(SMTP_HOST=""))
    assert exc_info.value.code == "EMAIL_NOT_CONFIGURED"
    assert "SMTP_HOST" in str(exc_info.value)


def test_missing_from_address_fails_with_email_not_configured() -> None:
    with pytest.raises(EmailNotConfiguredError) as exc_info:
        load_email_settings(_full_env(EMAIL_FROM_ADDRESS=""))
    assert exc_info.value.code == "EMAIL_NOT_CONFIGURED"
    assert "EMAIL_FROM_ADDRESS" in str(exc_info.value)


def test_partial_credentials_fail_cleanly() -> None:
    with pytest.raises(EmailNotConfiguredError, match="SMTP_USERNAME"):
        load_email_settings(_full_env(SMTP_PASSWORD=""))


def test_default_port_for_ssl_when_port_omitted() -> None:
    env = _full_env(SMTP_SECURITY="ssl")
    del env["SMTP_PORT"]
    settings = load_email_settings(env)
    assert settings.smtp_port == 465
    assert settings.smtp_security == SMTP_SECURITY_SSL


def test_none_security_is_accepted_when_explicit() -> None:
    settings = load_email_settings(_full_env(SMTP_SECURITY="none", SMTP_PORT="25"))
    assert settings.smtp_security == SMTP_SECURITY_NONE
    assert settings.smtp_port == 25


# --- MESSAGE BUILDING ---


def test_build_message_sets_recipient_from_subject_and_body() -> None:
    msg = build_message(
        to_address="user@example.com",
        subject="Password changed",
        text_body="Your password was changed.",
        from_address="no-reply@example.com",
        from_name="Hypatia",
    )
    assert msg["To"] == "user@example.com"
    assert msg["Subject"] == "Password changed"
    assert parseaddr(msg["From"]) == ("Hypatia", "no-reply@example.com")
    assert msg.get_content().strip() == "Your password was changed."


# --- STARTTLS / SSL / NONE ---


def test_starttls_connects_upgrades_authenticates_and_sends() -> None:
    mock_smtp = MagicMock()
    settings = _settings(smtp_security=SMTP_SECURITY_STARTTLS, smtp_port=587)

    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp) as ctor:
        send_email(
            to_address="user@example.com",
            subject="Hello",
            text_body="Body",
            settings=settings,
        )

    ctor.assert_called_once_with("smtp.example.com", 587, timeout=30.0)
    mock_smtp.starttls.assert_called_once_with()
    mock_smtp.login.assert_called_once_with("mailer", "secret-password")
    mock_smtp.send_message.assert_called_once()
    sent = mock_smtp.send_message.call_args.args[0]
    assert sent["To"] == "user@example.com"
    assert sent["Subject"] == "Hello"
    mock_smtp.quit.assert_called_once_with()


def test_ssl_uses_smtp_ssl_without_starttls() -> None:
    mock_smtp = MagicMock()
    settings = _settings(smtp_security=SMTP_SECURITY_SSL, smtp_port=465)

    with (
        patch("hypatia.services.email.sender.smtplib.SMTP_SSL", return_value=mock_smtp) as ssl_ctor,
        patch("hypatia.services.email.sender.smtplib.SMTP") as plain_ctor,
    ):
        send_email(
            to_address="user@example.com",
            subject="Hello",
            text_body="Body",
            settings=settings,
        )

    ssl_ctor.assert_called_once_with("smtp.example.com", 465, timeout=30.0)
    plain_ctor.assert_not_called()
    mock_smtp.starttls.assert_not_called()
    mock_smtp.login.assert_called_once_with("mailer", "secret-password")
    mock_smtp.send_message.assert_called_once()
    mock_smtp.quit.assert_called_once_with()


def test_none_uses_plain_smtp_without_starttls() -> None:
    """Plain SMTP (SMTP_SECURITY=none) — production should prefer starttls/ssl."""
    mock_smtp = MagicMock()
    settings = _settings(
        smtp_security=SMTP_SECURITY_NONE,
        smtp_port=25,
        smtp_username="",
        smtp_password="",
    )

    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp) as ctor:
        send_email(
            to_address="user@example.com",
            subject="Hello",
            text_body="Body",
            settings=settings,
        )

    ctor.assert_called_once_with("smtp.example.com", 25, timeout=30.0)
    mock_smtp.starttls.assert_not_called()
    mock_smtp.login.assert_not_called()
    mock_smtp.send_message.assert_called_once()
    mock_smtp.quit.assert_called_once_with()


def test_skips_authentication_when_credentials_absent() -> None:
    mock_smtp = MagicMock()
    settings = _settings(smtp_username="", smtp_password="")

    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp):
        send_email(
            to_address="user@example.com",
            subject="Hello",
            text_body="Body",
            settings=settings,
        )

    mock_smtp.login.assert_not_called()


# --- FAILURES ---


def test_smtp_exception_becomes_email_delivery_error() -> None:
    mock_smtp = MagicMock()
    mock_smtp.send_message.side_effect = smtplib.SMTPServerDisconnected("disconnected")

    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp):
        with pytest.raises(EmailDeliveryError) as exc_info:
            send_email(
                to_address="user@example.com",
                subject="Hello",
                text_body="Body",
                settings=_settings(),
            )

    err = exc_info.value
    assert err.code == "EMAIL_DELIVERY_FAILED"
    assert "secret-password" not in str(err)
    assert "secret-password" not in repr(err)
    mock_smtp.quit.assert_called_once_with()


def test_network_oserror_becomes_email_delivery_error_and_cleans_up() -> None:
    mock_smtp = MagicMock()
    mock_smtp.starttls.side_effect = OSError("connection reset")

    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp):
        with pytest.raises(EmailDeliveryError) as exc_info:
            send_email(
                to_address="user@example.com",
                subject="Hello",
                text_body="Body",
                settings=_settings(),
            )

    assert exc_info.value.code == "EMAIL_DELIVERY_FAILED"
    assert "secret-password" not in str(exc_info.value)
    assert "secret-password" not in repr(exc_info.value)
    # starttls failed inside _open_smtp before return; connection closed there.
    mock_smtp.close.assert_called_once_with()
    mock_smtp.quit.assert_not_called()


def test_connection_cleaned_up_when_quit_fails() -> None:
    mock_smtp = MagicMock()
    mock_smtp.quit.side_effect = OSError("already closed")

    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp):
        send_email(
            to_address="user@example.com",
            subject="Hello",
            text_body="Body",
            settings=_settings(),
        )

    mock_smtp.quit.assert_called_once_with()
    mock_smtp.close.assert_called_once_with()


def test_send_email_without_settings_uses_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _full_env().items():
        monkeypatch.setenv(key, value)

    mock_smtp = MagicMock()
    with patch("hypatia.services.email.sender.smtplib.SMTP", return_value=mock_smtp):
        send_email(
            to_address="user@example.com",
            subject="Hello",
            text_body="Body",
        )

    mock_smtp.send_message.assert_called_once()
