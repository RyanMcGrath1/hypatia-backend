"""Register URL blueprints on the Flask application.

Layout mirrors the Expo app's ``hooks/api/`` modules so each frontend client file
maps to one backend route package.
"""

from __future__ import annotations

from flask import Flask

from hypatia.routes.auth import bp as auth_bp
from hypatia.routes.economy import bp as economy_bp
from hypatia.routes.fec import bp as fec_bp
from hypatia.routes.health import bp as health_bp
from hypatia.routes.news import bp as news_bp


def register_blueprints(app: Flask) -> None:
    for blueprint in (health_bp, auth_bp, fec_bp, economy_bp, news_bp):
        app.register_blueprint(blueprint)
