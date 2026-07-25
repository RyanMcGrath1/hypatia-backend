"""Production SECRET_KEY fail-closed startup validation (audit finding #8)."""

from __future__ import annotations

import pytest

from hypatia import create_app
from hypatia.utils.settings import (
    INSECURE_DEVELOPMENT_SECRET_KEY,
    SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE,
    resolve_production_secret_key,
)

# Obvious fixture — not a real deployment secret.
_VALID_PRODUCTION_TEST_SECRET = "test-production-secret-key-fixture-not-real"


@pytest.fixture
def isolate_production_env(monkeypatch):
    """Neutralize dotenv and deployment env so tests do not use the host .env."""
    monkeypatch.setattr("hypatia.load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("HYPATIA_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)


def test_resolve_rejects_missing() -> None:
    with pytest.raises(RuntimeError, match="SECRET_KEY") as excinfo:
        resolve_production_secret_key(None)
    assert str(excinfo.value) == SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE
    assert INSECURE_DEVELOPMENT_SECRET_KEY not in str(excinfo.value)


def test_resolve_rejects_blank_and_whitespace() -> None:
    for raw in ("", "   ", "\t\n"):
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            resolve_production_secret_key(raw)


def test_resolve_rejects_development_placeholder() -> None:
    with pytest.raises(RuntimeError, match="SECRET_KEY") as excinfo:
        resolve_production_secret_key(INSECURE_DEVELOPMENT_SECRET_KEY)
    assert str(excinfo.value) == SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE
    assert INSECURE_DEVELOPMENT_SECRET_KEY not in str(excinfo.value)


def test_resolve_accepts_non_placeholder() -> None:
    assert (
        resolve_production_secret_key(_VALID_PRODUCTION_TEST_SECRET)
        == _VALID_PRODUCTION_TEST_SECRET
    )


def test_production_create_app_fails_when_secret_missing(
    isolate_production_env, monkeypatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY") as excinfo:
        create_app("production")
    assert str(excinfo.value) == SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE
    assert _VALID_PRODUCTION_TEST_SECRET not in str(excinfo.value)


def test_production_create_app_fails_on_development_placeholder(
    isolate_production_env, monkeypatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", INSECURE_DEVELOPMENT_SECRET_KEY)
    with pytest.raises(RuntimeError, match="SECRET_KEY") as excinfo:
        create_app("production")
    assert str(excinfo.value) == SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE
    assert INSECURE_DEVELOPMENT_SECRET_KEY not in str(excinfo.value)


def test_production_create_app_fails_on_blank_secret(
    isolate_production_env, monkeypatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "   ")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


def test_production_create_app_succeeds_with_explicit_secret(
    isolate_production_env, monkeypatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", _VALID_PRODUCTION_TEST_SECRET)
    # ProductionConfig has no DB default; provide a disposable URI so startup
    # can proceed past SECRET_KEY validation (import-time URI is not re-read).
    monkeypatch.setattr(
        "hypatia.utils.settings.Config.SQLALCHEMY_DATABASE_URI",
        "sqlite:///:memory:",
    )
    app = create_app("production")
    assert app.config["SECRET_KEY"] == _VALID_PRODUCTION_TEST_SECRET
    assert app.config["SECRET_KEY"] != INSECURE_DEVELOPMENT_SECRET_KEY
    assert app.config["DEBUG"] is False
    assert app.config["TESTING"] is False


def test_development_create_app_still_works_without_secret(
    isolate_production_env, monkeypatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    # Development must not fail closed on a missing production-grade secret.
    app = create_app("development")
    assert app.config["TESTING"] is False
    assert isinstance(app.config["SECRET_KEY"], str)
    assert app.config["SECRET_KEY"]


def test_testing_create_app_does_not_require_production_secret(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    app = create_app("testing")
    assert app.config["TESTING"] is True
    assert isinstance(app.config["SECRET_KEY"], str)
    assert app.config["SECRET_KEY"]
