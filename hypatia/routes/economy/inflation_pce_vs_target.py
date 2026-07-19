"""PCE YoY vs Fed target — ``GET /api/economy/inflation/pce-vs-target``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response
from hypatia.services.economy.pce_vs_target import build_pce_vs_target


@bp.get("/api/economy/inflation/pce-vs-target")
def economy_inflation_pce_vs_target():
    """FRED ``PCEPI`` and ``PCEPILFE`` YoY (``units=pc1``) vs the Fed's 2% target."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_pce_vs_target(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
