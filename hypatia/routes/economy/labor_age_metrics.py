"""Labor metrics by age — ``GET /api/economy/labor/age-metrics``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response, sector_window_from_request
from hypatia.services.economy import build_labor_age_metrics


@bp.get("/api/economy/labor/age-metrics")
def economy_labor_age_metrics():
    """Unemployment, labor force participation, and employment-population ratio by age (FRED LNS*)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    window, bad = sector_window_from_request()
    if bad:
        return bad
    assert window is not None
    obs_start, obs_end = window

    payload, all_network_failed = build_labor_age_metrics(
        api_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
