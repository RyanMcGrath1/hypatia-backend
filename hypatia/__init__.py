"""Hypatia Flask application factory and package root.

HTTP handlers live under ``hypatia.routes`` (grouped like Expo ``hooks/api/``).
Domain logic and upstream clients live under ``hypatia.services``. Root
``economy.py`` / ``news.py`` re-export services for tests and legacy imports.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from hypatia.extensions import db, limiter, migrate
from hypatia.routes import register_blueprints
from hypatia.utils.cors import init_cors
from hypatia.utils.error_handlers import register_error_handlers
from hypatia.utils.logging_config import configure_logging, register_request_logging
from hypatia.utils.settings import (
    ProductionConfig,
    get_config_class,
    resolve_production_secret_key,
)

# Project root (parent of the ``hypatia`` package).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(config_name: str | None = None) -> Flask:
    """Build and configure the Flask app.

    :param config_name: ``development``, ``production``, or ``testing``. When omitted,
        uses ``HYPATIA_ENV``, then ``FLASK_ENV``, then ``development``.
    """
    cfg_class = get_config_class(config_name)

    if not getattr(cfg_class, "TESTING", False):
        load_dotenv(_PROJECT_ROOT / ".env")

    app = Flask(__name__)
    app.config.from_object(cfg_class)

    # Production: re-read SECRET_KEY after dotenv and fail closed on
    # missing / blank / development placeholder. Import-time Config.SECRET_KEY
    # alone is not reliable for this check.
    if cfg_class is ProductionConfig:
        app.config["SECRET_KEY"] = resolve_production_secret_key()

    configure_logging(app)
    register_request_logging(app)
    register_error_handlers(app)
    init_cors(app)
    db.init_app(app)
    import hypatia.models  # noqa: F401 — register models with SQLAlchemy metadata

    migrate.init_app(app, db)
    limiter.init_app(app)
    register_blueprints(app)
    return app
