"""Thin FRED proxies — Expo ``fredObservations``."""

from __future__ import annotations

import time

import requests
from flask import jsonify, request

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response
from hypatia.logging_config import log_upstream
from hypatia.services.economy import FRED_OBSERVATIONS_URL, FRED_REQUEST_TIMEOUT

_FRED_OBSERVATIONS_FORWARD_PARAMS = frozenset(
    {
        "series_id",
        "realtime_start",
        "realtime_end",
        "observation_start",
        "observation_end",
        "units",
        "frequency",
        "aggregation_method",
        "output_type",
        "limit",
        "offset",
        "sort_order",
    }
)

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


@bp.get("/api/economy/fred/observations")
def fred_series_observations():
    """Proxy FRED ``GET /fred/series/observations``; ``api_key`` from env only."""
    series_id = request.args.get("series_id", "").strip()
    if not series_id:
        return jsonify({"error": "Query parameter 'series_id' is required"}), 400
    return _fred_observations_proxy(series_id=series_id)


@bp.get("/api/economy/fred/series/PAYEMS/delta")
def fred_payems_delta_series():
    """PAYEMS month-over-month deltas via FRED observations (``units=chg``)."""
    return _fred_observations_proxy(series_id=_PAYEMS_SERIES_ID, units="chg")
