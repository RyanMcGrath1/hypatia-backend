"""Civic API — Expo ``flaskMainApi`` civic helpers."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("civic", __name__)

from hypatia.routes.civic import routes  # noqa: E402, F401
