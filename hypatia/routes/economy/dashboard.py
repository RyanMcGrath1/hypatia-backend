"""Economy tab dashboard — Expo ``economyDashboardApi.fetchEconomyOverview``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import (
    fred_api_key_or_response,
    observation_end_from_request,
)
from hypatia.services.economy import build_economy_overview


@bp.get("/api/economy/dashboard")
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
