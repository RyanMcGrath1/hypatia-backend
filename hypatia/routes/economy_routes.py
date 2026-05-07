"""FRED-backed economy HTTP routes (business logic in ``economy`` package module)."""

from __future__ import annotations

import os

from flask import Blueprint, jsonify

from economy import build_economy_overview, build_economy_summary
from hypatia.http import missing_env_key_response
from hypatia.settings import Config

bp = Blueprint("economy", __name__)


@bp.get("/api/economy/summary")
def economy_summary():
    """Configured tiles: latest (and optional prior) observations."""
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_FRED)

    return jsonify(build_economy_summary(api_key)), 200


@bp.get("/api/economy/overview")
def economy_overview():
    """Overview series: recent observations per section."""
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_FRED)

    return jsonify(build_economy_overview(api_key)), 200
