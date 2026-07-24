"""Flask configuration objects (development, production, testing)."""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DEV_SQLITE_URI = f"sqlite:///{(_PROJECT_ROOT / 'hypatia.db').as_posix()}"


def truthy_from_str(raw: str | None, *, default: bool = False) -> bool:
    """True for common affirmative strings (env vars, query flags, form fields)."""
    if raw is None:
        return default
    v = raw.strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def env_truthy(name: str, *, default: bool = False) -> bool:
    return truthy_from_str(os.environ.get(name), default=default)


def env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


class Config:
    """Default settings shared across environments (override in subclasses)."""

    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    TESTING = False
    DEBUG = False
    JSON_SORT_KEYS = False

    # Upstream APIs (also on ``app.config`` after ``from_object``)
    OPENFEC_BASE = "https://api.open.fec.gov/v1"
    OPENFEC_NAMES_PER_PAGE_DEFAULT = 5
    OPENFEC_TYPEAHEAD_TIMEOUT_S = 12
    OPENFEC_DEFAULT_TIMEOUT_S = 30

    ENV_FRED = "FRED_API_KEY"
    ENV_GNEWS = "GNEWS_API_KEY"
    ENV_OPENFEC = "OPENFEC_API_KEY"
    ENV_DATABASE_URL = "DATABASE_URL"
    ENV_AUTH_SESSION_TTL_DAYS = "AUTH_SESSION_TTL_DAYS"
    ENV_SMTP_HOST = "SMTP_HOST"
    ENV_SMTP_PORT = "SMTP_PORT"
    ENV_SMTP_USERNAME = "SMTP_USERNAME"
    ENV_SMTP_PASSWORD = "SMTP_PASSWORD"
    ENV_SMTP_SECURITY = "SMTP_SECURITY"
    ENV_EMAIL_FROM_ADDRESS = "EMAIL_FROM_ADDRESS"
    ENV_EMAIL_FROM_NAME = "EMAIL_FROM_NAME"

    # Auth sessions (opaque Bearer tokens; TTL enforced server-side)
    AUTH_SESSION_TTL_DAYS = env_int(ENV_AUTH_SESSION_TTL_DAYS, default=30)

    # Outbound transactional email (SMTP). Resolved/validated at send time so
    # missing values raise EMAIL_NOT_CONFIGURED instead of attribute errors.
    # SMTP_SECURITY: starttls | ssl | none (default starttls; do not use none in
    # production unless deliberately configured for a trusted relay).
    SMTP_HOST = os.environ.get(ENV_SMTP_HOST, "")
    SMTP_PORT = os.environ.get(ENV_SMTP_PORT, "")
    SMTP_USERNAME = os.environ.get(ENV_SMTP_USERNAME, "")
    SMTP_PASSWORD = os.environ.get(ENV_SMTP_PASSWORD, "")
    SMTP_SECURITY = os.environ.get(ENV_SMTP_SECURITY, "starttls")
    EMAIL_FROM_ADDRESS = os.environ.get(ENV_EMAIL_FROM_ADDRESS, "")
    EMAIL_FROM_NAME = os.environ.get(ENV_EMAIL_FROM_NAME, "")
    SMTP_TIMEOUT_S = 30

    # SQLAlchemy (Flask-SQLAlchemy reads these from ``app.config``)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(ENV_DATABASE_URL)


class DevelopmentConfig(Config):
    """Local development: ``DEBUG`` from env (same signal as ``app.run(debug=...)``)."""

    DEBUG = env_truthy("FLASK_DEBUG") or env_truthy("DEBUG")
    SQLALCHEMY_DATABASE_URI = os.environ.get(Config.ENV_DATABASE_URL, _DEFAULT_DEV_SQLITE_URI)


class ProductionConfig(Config):
    """Production: no debug; set ``SECRET_KEY`` in the environment."""

    DEBUG = False
    PROPAGATE_EXCEPTIONS = False


class TestingConfig(Config):
    """Pytest: no dotenv side effects required; deterministic flags."""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(Config.ENV_DATABASE_URL, "sqlite:///:memory:")


CONFIG_MAP: dict[str, type[Config]] = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def resolve_config_name(explicit: str | None = None) -> str:
    """Pick config profile from ``explicit``, ``HYPATIA_ENV``, or ``FLASK_ENV``."""
    if explicit:
        return explicit.lower()
    for key in ("HYPATIA_ENV", "FLASK_ENV"):
        raw = os.environ.get(key, "").strip().lower()
        if raw:
            return raw
    return "development"


def get_config_class(config_name: str | None = None) -> type[Config]:
    key = resolve_config_name(config_name).lower()
    return CONFIG_MAP.get(key, DevelopmentConfig)
