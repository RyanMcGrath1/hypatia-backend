"""Economy API — mirrors Expo ``hooks/api/flaskMainApi``, ``economyDetailApi``, etc."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("economy", __name__)

from hypatia.routes.economy import (  # noqa: E402, F401
    dashboard,
    detail,
    fred,
    labor_age_metrics,
    labor_earnings_inflation,
    labor_sector,
)
