"""Average hourly earnings and CPI — ``GET /api/economy/labor/earnings-inflation``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response, sector_window_from_request
from hypatia.services.economy import build_labor_earnings_inflation


@bp.get("/api/economy/labor/earnings-inflation")
def economy_labor_earnings_inflation():
    """FRED ``CES0500000003`` (average hourly earnings) and ``CPIAUCSL`` (CPI inflation)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    window, bad = sector_window_from_request()
    if bad:
        return bad
    assert window is not None
    obs_start, obs_end = window

    payload, all_network_failed = build_labor_earnings_inflation(
        api_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
