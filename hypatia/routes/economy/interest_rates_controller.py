"""Interest rates controller — Fed funds target and key rate metrics.

Base path: ``/api/economy/rates`` (blueprint ``url_prefix``). Routes in this module are
relative, e.g. ``/fed-funds-target`` → ``GET /api/economy/rates/fed-funds-target``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from hypatia.routes.economy._common import fred_api_key_or_response, sector_window_from_request
from hypatia.services.economy.fed_funds_target import build_fed_funds_target
from hypatia.services.economy.rates_key_metrics import build_rates_key_metrics

bp = Blueprint("interest_rates_controller", __name__, url_prefix="/api/economy/rates")


@bp.get("/fed-funds-target")
def economy_rates_fed_funds_target():
    """FRED ``DFEDTARL`` and ``DFEDTARU`` — FOMC federal funds target range."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    window, bad = sector_window_from_request()
    if bad:
        return bad
    assert window is not None
    obs_start, obs_end = window

    payload, all_network_failed = build_fed_funds_target(
        api_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200


@bp.get("/key-metrics")
def economy_rates_key_metrics():
    """FRED ``DGS10``, ``MORTGAGE30US``, and ``DGS2`` — latest treasury and mortgage rates."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_rates_key_metrics(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
