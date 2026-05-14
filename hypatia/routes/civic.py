"""Google Civic Information API proxy routes."""

from __future__ import annotations

import os
import time

import requests
from flask import Blueprint, jsonify, request

from hypatia.http import missing_env_key_response
from hypatia.logging_config import log_upstream
from hypatia.settings import Config

bp = Blueprint("civic", __name__)


@bp.get("/api/civic/divisions-by-address")
def civic_divisions_by_address():
    """OCD division IDs for an address (``divisionsByAddress``)."""
    api_key = os.environ.get(Config.ENV_GOOGLE_CIVIC, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_GOOGLE_CIVIC)

    address = request.args.get("address", "").strip()
    if not address:
        return jsonify({"error": "Query parameter 'address' is required"}), 400

    url = f"{Config.GOOGLE_CIVIC_BASE}/divisionsByAddress"
    t0 = time.perf_counter()
    resp = requests.get(
        url,
        params={"address": address, "key": api_key},
        timeout=Config.GOOGLE_CIVIC_TIMEOUT_S,
    )
    log_upstream(
        "hypatia.upstream",
        service="google_civic",
        endpoint="divisionsByAddress",
        status_code=resp.status_code,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        response_bytes=len(resp.content),
    )
    try:
        data = resp.json()
    except ValueError:
        return jsonify({"error": "Invalid response from Google Civic API"}), 502
    return jsonify(data), resp.status_code


@bp.get("/api/civic/representatives")
def civic_representatives_gone():
    """Representatives API was retired in 2025; 410 with pointer to divisions-by-address."""
    return jsonify(
        {
            "error": "The Google Civic Representatives API is no longer available.",
            "use_instead": "/api/civic/divisions-by-address",
            "hint": (
                "Use GET /api/civic/divisions-by-address?address=... for OCD division IDs "
                "(see Google Civic docs)."
            ),
        }
    ), 410
