"""Economy tab + sector dashboards — Expo ``flaskMainApi.fetchEconomyOverview``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import (
    fred_api_key_or_response,
    observation_end_from_request,
    sector_window_from_request,
)
from hypatia.services.economy import (
    build_economy_overview,
    build_economy_overview_sector,
    resolve_economy_dashboard_sector,
)


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


@bp.get("/api/economy/<sector_id>/dashboard")
def economy_sector_dashboard(sector_id: str):
    """One overview section. Default FRED window is YTD (UTC); optional date range overrides."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    section_key = resolve_economy_dashboard_sector(sector_id)
    if section_key is None:
        return (
            jsonify(
                {
                    "error": "Unknown economy sector",
                    "hint": (
                        "Use a section id (gdp, labor, inflation, housing, consumer_spending, "
                        "interest_rates) or app aliases consumer, rates"
                    ),
                }
            ),
            404,
        )

    window, bad = sector_window_from_request()
    if bad:
        return bad
    assert window is not None
    obs_start, obs_end = window

    payload = build_economy_overview_sector(
        api_key,
        section_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    return jsonify(payload), 200
