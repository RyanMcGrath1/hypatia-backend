"""Rates key metrics — ``GET /api/economy/rates/key-metrics``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response
from hypatia.services.economy.rates_key_metrics import build_rates_key_metrics


@bp.get("/api/economy/rates/key-metrics")
def economy_rates_key_metrics():
    """FRED ``DGS10``, ``MORTGAGE30US``, and ``DGS2`` — latest treasury and mortgage rates."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_rates_key_metrics(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
