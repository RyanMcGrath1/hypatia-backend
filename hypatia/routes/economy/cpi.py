"""Recent CPI — ``GET /api/economy/cpi``."""

from __future__ import annotations

from flask import jsonify

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response
from hypatia.services.economy import build_cpi_recent


@bp.get("/api/economy/cpi")
def economy_cpi_recent():
    """Last 5 months of FRED ``CPIAUCSL`` (Consumer Price Index), newest first."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, status = build_cpi_recent(api_key)
    return jsonify(payload), status
