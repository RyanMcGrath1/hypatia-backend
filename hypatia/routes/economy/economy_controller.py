"""Economy dashboard controller — Expo ``economyDashboardApi.fetchEconomyOverview``.

Base path: ``/api/economy`` (blueprint ``url_prefix``). Routes in this module are relative,
e.g. ``/dashboard`` → ``GET /api/economy/dashboard``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from hypatia.routes.economy._common import (
    fred_api_key_or_response,
    observation_end_from_request,
)
from hypatia.services.economy import build_economy_overview

# /api/economy
bp = Blueprint("economy_controller", __name__, url_prefix="/api/economy")


@bp.get("/dashboard") # /api/economy/dashboard
def economy_dashboard():
    """Economy tab snapshot: recent FRED observations per section (``as_of``, ``sections``)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    observation_end, bad = observation_end_from_request()
    if bad:
        return bad

    payload = build_economy_overview(
        api_key,
        observation_end=observation_end,
    )
    return jsonify(payload), 200
