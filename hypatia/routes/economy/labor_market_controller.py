"""Labor market controller — payroll, PAYEMS deltas, and related labor FRED routes.

Base path: ``/api/economy/labor`` (blueprint ``url_prefix``). Routes in this module are
relative, e.g. ``/sector`` → ``GET /api/economy/labor/sector``.
"""

from __future__ import annotations

import time

import requests
from flask import Blueprint, jsonify, request

from hypatia.models import FredObservationParam, FredUnitsMode
from hypatia.routes.economy._common import fred_api_key_or_response, sector_window_from_request
from hypatia.services.economy import (
    FRED_OBSERVATIONS_URL,
    FRED_REQUEST_TIMEOUT,
    build_employment_sectors,
    build_labor_earnings_inflation,
    build_labor_age_metrics,
)
from hypatia.utils.logging_config import log_upstream

bp = Blueprint("labor_market_controller", __name__, url_prefix="/api/economy/labor")

_FRED_OBSERVATIONS_FORWARD_PARAMS = FredObservationParam.values()

_FRED_OBS_DEFAULT_LIMIT = 60
_FRED_OBS_LIMIT_MAX = 10_000
_PAYEMS_SERIES_ID = "PAYEMS"


def _fred_observations_proxy(*, series_id: str, units: str | None = None):
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    observation_start = request.args.get("observation_start", "").strip()
    params: dict[str, str] = {
        "api_key": api_key,
        "file_type": "json",
        "series_id": series_id,
    }
    if units:
        params["units"] = units
    if observation_start:
        params["observation_start"] = observation_start

    limit_raw = request.args.get("limit", "").strip()
    if limit_raw:
        try:
            lim = int(limit_raw, 10)
        except ValueError:
            return jsonify({"error": "Query parameter 'limit' must be an integer"}), 400
        if lim < 1:
            return jsonify({"error": "Query parameter 'limit' must be >= 1"}), 400
        params["limit"] = str(min(lim, _FRED_OBS_LIMIT_MAX))
    else:
        params["limit"] = str(_FRED_OBS_DEFAULT_LIMIT)

    skip = {"series_id", "limit", "observation_start"}
    if units:
        skip = skip | {"units"}
    for key in _FRED_OBSERVATIONS_FORWARD_PARAMS:
        if key in skip:
            continue
        raw = request.args.get(key, "").strip()
        if raw:
            params[key] = raw

    t0 = time.perf_counter()
    resp = requests.get(FRED_OBSERVATIONS_URL, params=params, timeout=FRED_REQUEST_TIMEOUT)
    log_upstream(
        "hypatia.upstream",
        service="fred",
        endpoint="series/observations",
        status_code=resp.status_code,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        response_bytes=len(resp.content),
    )
    try:
        data = resp.json()
    except ValueError:
        return jsonify({"error": "Invalid response from FRED API"}), 502
    return jsonify(data), resp.status_code


@bp.get("/payems/delta") # /api/economy/labor/payems/delta
def labor_payems_delta_series():
    """Jobs created/destroyed month-over-month (PAYEMS via FRED ``units=chg``)."""
    return _fred_observations_proxy(series_id=_PAYEMS_SERIES_ID, units=FredUnitsMode.CHG.value)


@bp.get("/sector") # /api/economy/labor/sector
def economy_labor_sector():
    """Employment levels by industry (sixteen FRED payroll series)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    window, bad = sector_window_from_request()
    if bad:
        return bad
    assert window is not None
    obs_start, obs_end = window

    payload, all_network_failed = build_employment_sectors(
        api_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200


@bp.get("/earnings-inflation") # /api/economy/labor/earnings-inflation
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


@bp.get("/age-metrics") # /api/economy/labor/age-metrics
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