"""Inflation controller — CPI components (and related inflation routes).

Base path: ``/api/economy/inflation`` (blueprint ``url_prefix``). Routes in this module are
relative, e.g. ``/cpi-components`` → ``GET /api/economy/inflation/cpi-components``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from hypatia.routes.economy._common import fred_api_key_or_response
from hypatia.services.economy.cpi_components import build_cpi_components
from hypatia.services.economy import build_cpi_recent
from hypatia.services.economy.pce_vs_target import build_pce_vs_target

bp = Blueprint("inflation_controller", __name__, url_prefix="/api/economy/inflation")


@bp.get("/cpi") # /api/economy/inflation/cpi
def economy_inflation_cpi():
    """Last 5 months of FRED ``CPIAUCSL`` (Consumer Price Index), newest first."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, status = build_cpi_recent(api_key)
    return jsonify(payload), status


@bp.get("/cpi-components") # /api/economy/inflation/cpi-components
def economy_inflation_cpi_components():
    """Headline ``CPIAUCSL`` and CPI component YoY (``units=pc1``)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_cpi_components(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200


@bp.get("/pce-vs-target") # /api/economy/inflation/pce-vs-target
def economy_inflation_pce_vs_target():
    """PCE YoY vs Fed target (``units=pc1``)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_pce_vs_target(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200