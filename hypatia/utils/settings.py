"""Flask configuration objects (development, production, testing)."""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DEV_SQLITE_URI = f"sqlite:///{(_PROJECT_ROOT / 'hypatia.db').as_posix()}"

# Local/dev fallback only. Production must never start with this value.
INSECURE_DEVELOPMENT_SECRET_KEY = "dev-insecure-change-me"
SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE = (
    "SECRET_KEY must be explicitly configured for production."
)


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


def resolve_production_secret_key(
    raw: str | None = None,
) -> str:
    """Return a production SECRET_KEY or raise if missing/blank/placeholder.

    Reads ``SECRET_KEY`` from the environment when ``raw`` is omitted so
    validation runs at app startup (after dotenv), not only at class import.
    Never includes the secret value in the exception message.
    """
    if raw is None:
        raw = os.environ.get("SECRET_KEY")
    if raw is None or not str(raw).strip():
        raise RuntimeError(SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE)
    secret = str(raw)
    if secret.strip() == INSECURE_DEVELOPMENT_SECRET_KEY:
        raise RuntimeError(SECRET_KEY_PRODUCTION_REQUIRED_MESSAGE)
    return secret


class Config:
    """Default settings shared across environments (override in subclasses)."""

    # Flask
    # Import-time default for development/testing. Production re-resolves and
    # validates SECRET_KEY at create_app() after dotenv load (see
    # ``resolve_production_secret_key``).
    SECRET_KEY = os.environ.get("SECRET_KEY", INSECURE_DEVELOPMENT_SECRET_KEY)
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
    ENV_TOTP_ENCRYPTION_KEY = "TOTP_ENCRYPTION_KEY"
    ENV_TOTP_ISSUER_NAME = "TOTP_ISSUER_NAME"
    ENV_TOTP_SETUP_TTL_SECONDS = "TOTP_SETUP_TTL_SECONDS"
    ENV_TOTP_LOGIN_CHALLENGE_TTL_MINUTES = "TOTP_LOGIN_CHALLENGE_TTL_MINUTES"
    ENV_TOTP_LOGIN_MAX_ATTEMPTS = "TOTP_LOGIN_MAX_ATTEMPTS"
    ENV_AUTH_RATE_LIMIT_STORAGE_URI = "AUTH_RATE_LIMIT_STORAGE_URI"
    ENV_AUTH_LOGIN_ACCOUNT_LIMIT = "AUTH_LOGIN_ACCOUNT_LIMIT"
    ENV_AUTH_LOGIN_ACCOUNT_WINDOW_MINUTES = "AUTH_LOGIN_ACCOUNT_WINDOW_MINUTES"
    ENV_AUTH_LOGIN_IP_LIMIT = "AUTH_LOGIN_IP_LIMIT"
    ENV_AUTH_LOGIN_IP_WINDOW_MINUTES = "AUTH_LOGIN_IP_WINDOW_MINUTES"
    ENV_AUTH_TOTP_ACCOUNT_LIMIT = "AUTH_TOTP_ACCOUNT_LIMIT"
    ENV_AUTH_TOTP_ACCOUNT_WINDOW_MINUTES = "AUTH_TOTP_ACCOUNT_WINDOW_MINUTES"
    ENV_AUTH_TOTP_IP_LIMIT = "AUTH_TOTP_IP_LIMIT"
    ENV_AUTH_TOTP_IP_WINDOW_MINUTES = "AUTH_TOTP_IP_WINDOW_MINUTES"
    ENV_SMTP_HOST = "SMTP_HOST"
    ENV_SMTP_PORT = "SMTP_PORT"
    ENV_SMTP_USERNAME = "SMTP_USERNAME"
    ENV_SMTP_PASSWORD = "SMTP_PASSWORD"
    ENV_SMTP_SECURITY = "SMTP_SECURITY"
    ENV_EMAIL_FROM_ADDRESS = "EMAIL_FROM_ADDRESS"
    ENV_EMAIL_FROM_NAME = "EMAIL_FROM_NAME"
    ENV_EMAIL_CHANGE_TOKEN_TTL_HOURS = "EMAIL_CHANGE_TOKEN_TTL_HOURS"
    ENV_EMAIL_CHANGE_VERIFY_URL = "EMAIL_CHANGE_VERIFY_URL"

    # Auth sessions (opaque Bearer tokens; TTL enforced server-side)
    AUTH_SESSION_TTL_DAYS = env_int(ENV_AUTH_SESSION_TTL_DAYS, default=30)

    # TOTP MFA — Fernet key must be supplied via environment (no production default).
    # Do not generate a new key on each startup; enrolled secrets would become undecryptable.
    TOTP_ENCRYPTION_KEY = os.environ.get(ENV_TOTP_ENCRYPTION_KEY, "")
    TOTP_ISSUER_NAME = os.environ.get(ENV_TOTP_ISSUER_NAME, "Hypatia")
    # Incomplete (disabled) enrollment must be confirmed within this window.
    TOTP_SETUP_TTL_SECONDS = env_int(ENV_TOTP_SETUP_TTL_SECONDS, default=900)
    TOTP_LOGIN_CHALLENGE_TTL_MINUTES = env_int(
        ENV_TOTP_LOGIN_CHALLENGE_TTL_MINUTES, default=5
    )
    TOTP_LOGIN_MAX_ATTEMPTS = env_int(ENV_TOTP_LOGIN_MAX_ATTEMPTS, default=5)

    # Auth rate limiting (Flask-Limiter). Counts successful and failed requests
    # that reach the decorated endpoints. Development/testing may use in-process
    # memory storage; multi-worker/multi-instance production must set a shared
    # backend (e.g. redis://...) via AUTH_RATE_LIMIT_STORAGE_URI.
    # Client IP is request.remote_addr — do not trust X-Forwarded-For unless a
    # trusted reverse-proxy (e.g. ProxyFix) is explicitly configured.
    AUTH_LOGIN_ACCOUNT_LIMIT = env_int(ENV_AUTH_LOGIN_ACCOUNT_LIMIT, default=10)
    AUTH_LOGIN_ACCOUNT_WINDOW_MINUTES = env_int(
        ENV_AUTH_LOGIN_ACCOUNT_WINDOW_MINUTES, default=15
    )
    AUTH_LOGIN_IP_LIMIT = env_int(ENV_AUTH_LOGIN_IP_LIMIT, default=30)
    AUTH_LOGIN_IP_WINDOW_MINUTES = env_int(
        ENV_AUTH_LOGIN_IP_WINDOW_MINUTES, default=15
    )
    AUTH_TOTP_ACCOUNT_LIMIT = env_int(ENV_AUTH_TOTP_ACCOUNT_LIMIT, default=10)
    AUTH_TOTP_ACCOUNT_WINDOW_MINUTES = env_int(
        ENV_AUTH_TOTP_ACCOUNT_WINDOW_MINUTES, default=15
    )
    AUTH_TOTP_IP_LIMIT = env_int(ENV_AUTH_TOTP_IP_LIMIT, default=30)
    AUTH_TOTP_IP_WINDOW_MINUTES = env_int(
        ENV_AUTH_TOTP_IP_WINDOW_MINUTES, default=15
    )
    # Flask-Limiter config keys (read by limiter.init_app).
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get(
        ENV_AUTH_RATE_LIMIT_STORAGE_URI, "memory://"
    )
    # Do not emit X-RateLimit-* counter headers (avoid disclosing budgets).
    # Retry-After on 429 is set by the error handler when available.
    RATELIMIT_HEADERS_ENABLED = False

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

    # Email change: dual-confirmation opaque tokens (TTL enforced server-side).
    # EMAIL_CHANGE_VERIFY_URL is the frontend/deep-link base; the raw token is
    # appended as ?token=... when building confirmation links (never log those URLs).
    EMAIL_CHANGE_TOKEN_TTL_HOURS = env_int(
        ENV_EMAIL_CHANGE_TOKEN_TTL_HOURS, default=8
    )
    EMAIL_CHANGE_VERIFY_URL = os.environ.get(
        ENV_EMAIL_CHANGE_VERIFY_URL, "hypatia://verify-email-change"
    )

    # SQLAlchemy (Flask-SQLAlchemy reads these from ``app.config``)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(ENV_DATABASE_URL)


class DevelopmentConfig(Config):
    """Local development: ``DEBUG`` from env (same signal as ``app.run(debug=...)``)."""

    DEBUG = env_truthy("FLASK_DEBUG") or env_truthy("DEBUG")
    SQLALCHEMY_DATABASE_URI = os.environ.get(Config.ENV_DATABASE_URL, _DEFAULT_DEV_SQLITE_URI)


class ProductionConfig(Config):
    """Production: no debug; requires an explicit non-placeholder ``SECRET_KEY``.

    ``create_app("production")`` re-reads and validates ``SECRET_KEY`` after
    dotenv load so startup fails closed if the value is missing, blank, or the
    development placeholder.
    """

    DEBUG = False
    PROPAGATE_EXCEPTIONS = False


class TestingConfig(Config):
    """Pytest: no dotenv side effects required; deterministic flags."""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(Config.ENV_DATABASE_URL, "sqlite:///:memory:")
    # Deterministic valid Fernet key (32 zero bytes, url-safe base64). Tests only.
    TOTP_ENCRYPTION_KEY = os.environ.get(
        Config.ENV_TOTP_ENCRYPTION_KEY,
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    TOTP_ISSUER_NAME = os.environ.get(Config.ENV_TOTP_ISSUER_NAME, "Hypatia")
    TOTP_SETUP_TTL_SECONDS = env_int(
        Config.ENV_TOTP_SETUP_TTL_SECONDS, default=900
    )
    TOTP_LOGIN_CHALLENGE_TTL_MINUTES = env_int(
        Config.ENV_TOTP_LOGIN_CHALLENGE_TTL_MINUTES, default=5
    )
    TOTP_LOGIN_MAX_ATTEMPTS = env_int(Config.ENV_TOTP_LOGIN_MAX_ATTEMPTS, default=5)


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
