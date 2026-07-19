"""Rates key metrics — ``GET /api/economy/rates/key-metrics``."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from hypatia.utils.logging_config import log_upstream
from hypatia.services.economy.core import FRED_OBSERVATIONS_URL, FRED_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

RATES_KEY_METRICS_FETCH_LIMIT = 1

_NETWORK_ERROR_PREFIXES = (
    "FRED request timed out",
    "FRED request failed",
)

RATES_KEY_METRICS: tuple[tuple[str, str, str], ...] = (
    ("DGS10", "10Y Treasury", "Benchmark long rate"),
    ("MORTGAGE30US", "30Y Mortgage", "Constrained affordability"),
    ("DGS2", "2Y Treasury", "Policy-sensitive yield"),
)


def _parse_level_value(raw: Any) -> float | None:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        n = float(raw)
        return round(n, 2) if n == n else None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s == ".":
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return round(n, 2) if n == n else None


def _fetch_fred_latest(api_key: str, series_id: str) -> dict[str, Any]:
    """Latest observation for one FRED level series."""
    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(RATES_KEY_METRICS_FETCH_LIMIT),
    }
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning("FRED rates key metric request timed out series_id=%s", series_id)
        return {"error": "FRED request timed out"}
    except requests.RequestException as exc:
        logger.warning(
            "FRED rates key metric request failed series_id=%s error=%s",
            series_id,
            exc,
        )
        return {"error": f"FRED request failed: {exc!s}"}

    log_upstream(
        "hypatia.upstream",
        service="fred",
        endpoint="series/observations",
        status_code=resp.status_code,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        response_bytes=len(resp.content),
    )

    if not resp.ok:
        err_msg = f"FRED returned HTTP {resp.status_code}"
        try:
            err_body = resp.json()
            if isinstance(err_body.get("error_message"), str):
                err_msg = err_body["error_message"]
        except ValueError:
            pass
        return {"error": err_msg}

    try:
        payload = resp.json()
    except ValueError:
        return {"error": "Invalid JSON from FRED"}

    raw_obs = payload.get("observations")
    if not isinstance(raw_obs, list) or not raw_obs:
        return {"error": "No observations in FRED response"}

    for row in raw_obs:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        value = _parse_level_value(row.get("value"))
        if value is None:
            continue
        return {"value": value, "observation_date": d}

    return {"error": "No usable observations in FRED response"}


def _metric_payload(
    *,
    series_id: str,
    label: str,
    note: str,
    fetch_result: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "series_id": series_id,
        "label": label,
        "note": note,
        "value": fetch_result.get("value"),
        "observation_date": fetch_result.get("observation_date"),
    }
    if fetch_result.get("error"):
        body["error"] = fetch_result["error"]
        body["value"] = None
        body["observation_date"] = None
    return body


def build_rates_key_metrics(api_key: str) -> tuple[dict[str, Any], bool]:
    """Fetch latest treasury yields and mortgage rate for the rates detail widget.

    Returns ``(payload, all_network_failed)``. ``all_network_failed`` is true only
    when every series hit a network-level error (timeout/connection).
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    results: dict[str, dict[str, Any]] = {}
    workers = max(1, len(RATES_KEY_METRICS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_fred_latest, api_key, series_id): series_id
            for series_id, _label, _note in RATES_KEY_METRICS
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()

    network_failed = 0
    for series_id, _label, _note in RATES_KEY_METRICS:
        err = results[series_id].get("error")
        if err and str(err).startswith(_NETWORK_ERROR_PREFIXES):
            network_failed += 1

    metrics = [
        _metric_payload(
            series_id=series_id,
            label=label,
            note=note,
            fetch_result=results[series_id],
        )
        for series_id, label, note in RATES_KEY_METRICS
    ]

    payload: dict[str, Any] = {
        "as_of": as_of,
        "metrics": metrics,
    }
    return payload, network_failed == len(RATES_KEY_METRICS)
