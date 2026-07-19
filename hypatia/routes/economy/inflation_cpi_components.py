"""CPI component YoY breakdown — ``GET /api/economy/inflation/cpi-components``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response
from hypatia.services.economy.cpi_components import build_cpi_components


@bp.get("/api/economy/inflation/cpi-components")
def economy_inflation_cpi_components():
    """Headline ``CPIAUCSL`` and CPI component YoY (``units=pc1``)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_cpi_components(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
