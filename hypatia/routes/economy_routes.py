"""FRED-backed economy HTTP routes (business logic in ``economy`` package module)."""

from __future__ import annotations

import os
import re
import time

import requests
from flask import Blueprint, jsonify, request

from economy import (
    FRED_OBSERVATIONS_URL,
    FRED_REQUEST_TIMEOUT,
    build_economy_overview,
    build_economy_overview_sector,
    resolve_economy_dashboard_sector,
    resolve_sector_dashboard_observation_window,
)
from hypatia.http import missing_env_key_response
from hypatia.logging_config import log_upstream
from hypatia.settings import Config

bp = Blueprint("economy", __name__)

_OVERVIEW_OBSERVATION_END_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Whitelisted query keys forwarded to FRED ``series/observations`` (``api_key`` from env only).
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


@bp.get("/api/economy/overview")
def economy_overview():
    """Economy tab snapshot: recent FRED observations per section (`as_of`, `sections`)."""
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_FRED)

    observation_end = (request.args.get("observation_end") or "").strip()
    if observation_end and _OVERVIEW_OBSERVATION_END_RE.fullmatch(observation_end) is None:
        return (
            jsonify(
                {
                    "error": "Invalid observation_end",
                    "hint": "Use YYYY-MM-DD (e.g. 2025-11-01)",
                }
            ),
            400,
        )

    payload = build_economy_overview(
        api_key,
        observation_end=observation_end or None,
    )
    return jsonify(payload), 200


@bp.get("/api/economy/<sector_id>/dashboard")
def economy_sector_dashboard(sector_id: str):
    """One overview section. Default FRED window is **YTD (UTC)**; optional ``observation_start`` /
    ``observation_end`` (``YYYY-MM-DD``, inclusive) override.
    """
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_FRED)

    section_key = resolve_economy_dashboard_sector(sector_id)
    if section_key is None:
        return (
            jsonify(
                {
                    "error": "Unknown economy sector",
                    "hint": (
                        "Use a section id (gdp, labor, inflation, housing, consumer_spending, "
                        "interest_rates) or app aliases consumer, rates"
                    ),
                }
            ),
            404,
        )

    try:
        obs_start, obs_end = resolve_sector_dashboard_observation_window(
            request.args.get("observation_start"),
            request.args.get("observation_end"),
        )
    except ValueError as exc:
        return (
            jsonify(
                {
                    "error": str(exc),
                    "hint": "Use observation_start / observation_end as YYYY-MM-DD (default: YTD UTC).",
                }
            ),
            400,
        )

    payload = build_economy_overview_sector(
        api_key,
        section_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    return jsonify(payload), 200


@bp.get("/api/economy/fred/observations")
def fred_series_observations():
    """Proxy FRED ``GET /fred/series/observations``; ``api_key`` comes from ``FRED_API_KEY`` only.

    Required query param: ``series_id``. ``observation_start`` is optional (omit with
    ``sort_order=desc`` and ``limit`` to fetch the newest observations). Optional ``limit``
    (default 60, max 10000). Other FRED observations parameters may be forwarded when whitelisted.
    See https://fred.stlouisfed.org/docs/api/fred/series_observations.html
    """
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_FRED)

    series_id = request.args.get("series_id", "").strip()
    observation_start = request.args.get("observation_start", "").strip()
    if not series_id:
        return jsonify({"error": "Query parameter 'series_id' is required"}), 400

    params: dict[str, str] = {
        "api_key": api_key,
        "file_type": "json",
        "series_id": series_id,
    }
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

    for key in _FRED_OBSERVATIONS_FORWARD_PARAMS:
        if key in ("series_id", "limit", "observation_start"):
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


@bp.get("/api/economy/fred/series/PAYEMS/delta")
def fred_payems_delta_series():
    """Proxy PAYEMS monthly delta series via FRED observations (`units=chg`).

    Optional query params: ``observation_start`` and ``limit`` (default 60, max 10000),
    plus forwarded FRED observation args like ``sort_order``.
    """
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_FRED)

    observation_start = request.args.get("observation_start", "").strip()
    params: dict[str, str] = {
        "api_key": api_key,
        "file_type": "json",
        "series_id": _PAYEMS_SERIES_ID,
        "units": "chg",
    }
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

    for key in _FRED_OBSERVATIONS_FORWARD_PARAMS:
        if key in ("series_id", "units", "limit", "observation_start"):
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
