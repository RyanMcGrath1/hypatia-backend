"""News API — Expo ``newsApi``."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("news", __name__)

from hypatia.routes.news import routes  # noqa: E402, F401
