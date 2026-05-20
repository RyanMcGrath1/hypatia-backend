"""Economy API — mirrors Expo ``hooks/api/flaskMainApi``, ``economyDetailApi``, etc."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("economy", __name__)

from hypatia.routes.economy import dashboard, detail, fred, labor_sector  # noqa: E402, F401
