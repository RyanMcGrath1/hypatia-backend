"""Register all URL blueprints on the Flask application."""

from __future__ import annotations

from flask import Flask

from hypatia.routes.civic import bp as civic_bp
from hypatia.routes.economy_routes import bp as economy_bp
from hypatia.routes.fec import bp as fec_bp
from hypatia.routes.health import bp as health_bp
from hypatia.routes.news_routes import bp as news_bp


def register_blueprints(app: Flask) -> None:
    for blueprint in (health_bp, civic_bp, fec_bp, economy_bp, news_bp):
        app.register_blueprint(blueprint)
