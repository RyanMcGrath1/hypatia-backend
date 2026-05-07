"""Flask configuration objects (development, production, testing)."""

from __future__ import annotations

import os


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


class Config:
    """Default settings shared across environments (override in subclasses)."""

    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    TESTING = False
    DEBUG = False
    JSON_SORT_KEYS = False

    # Upstream APIs (also on ``app.config`` after ``from_object``)
    GOOGLE_CIVIC_BASE = "https://www.googleapis.com/civicinfo/v2"
    GOOGLE_CIVIC_TIMEOUT_S = 30

    OPENFEC_BASE = "https://api.open.fec.gov/v1"
    OPENFEC_NAMES_PER_PAGE_DEFAULT = 5
    OPENFEC_TYPEAHEAD_TIMEOUT_S = 12
    OPENFEC_DEFAULT_TIMEOUT_S = 30

    ENV_GOOGLE_CIVIC = "GOOGLE_CIVIC_API_KEY"
    ENV_FRED = "FRED_API_KEY"
    ENV_GNEWS = "GNEWS_API_KEY"
    ENV_OPENFEC = "OPENFEC_API_KEY"


class DevelopmentConfig(Config):
    """Local development: ``DEBUG`` from env (same signal as ``app.run(debug=...)``)."""

    DEBUG = env_truthy("FLASK_DEBUG") or env_truthy("DEBUG")


class ProductionConfig(Config):
    """Production: no debug; set ``SECRET_KEY`` in the environment."""

    DEBUG = False
    PROPAGATE_EXCEPTIONS = False


class TestingConfig(Config):
    """Pytest: no dotenv side effects required; deterministic flags."""

    TESTING = True
    DEBUG = False


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
