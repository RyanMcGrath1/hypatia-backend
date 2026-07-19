"""PCE YoY vs Fed target — ``GET /api/economy/inflation/pce-vs-target``."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from hypatia.logging_config import log_upstream
from hypatia.services.economy.core import FRED_OBSERVATIONS_URL, FRED_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

FED_PCE_INFLATION_TARGET = 2.0

PCE_HEADLINE_SERIES_ID = "PCEPI"
PCE_HEADLINE_LABEL = "PCE Headline"
PCE_CORE_SERIES_ID = "PCEPILFE"
PCE_CORE_LABEL = "Core PCE"

PCE_YOY_UNITS = "pc1"
PCE_YOY_FETCH_LIMIT = 2

_NETWORK_ERROR_PREFIXES = (
    "FRED request timed out",
    "FRED request failed",
)


def _parse_pc1_value(raw: Any) -> float | None:
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        n = float(raw)
        return n if n == n else None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s == ".":
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n == n else None


def _fetch_fred_pc1_latest(api_key: str, series_id: str) -> dict[str, Any]:
    """Latest percent-change-from-year-ago observation for one FRED series."""
    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "units": PCE_YOY_UNITS,
        "sort_order": "desc",
        "limit": str(PCE_YOY_FETCH_LIMIT),
    }
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning("FRED PCE YoY request timed out series_id=%s", series_id)
        return {"error": "FRED request timed out"}
    except requests.RequestException as exc:
        logger.warning("FRED PCE YoY request failed series_id=%s error=%s", series_id, exc)
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

    collected: list[tuple[str, float]] = []
    for row in raw_obs:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        value = _parse_pc1_value(row.get("value"))
        if value is None:
            continue
        collected.append((d, round(value, 2)))
        if len(collected) >= PCE_YOY_FETCH_LIMIT:
            break

    if not collected:
        return {"error": "No usable observations in FRED response"}

    out: dict[str, Any] = {
        "value": collected[0][1],
        "observation_date": collected[0][0],
    }
    if len(collected) >= 2:
        out["previous_value"] = collected[1][1]
        out["previous_observation_date"] = collected[1][0]
    return out


def _metric_payload(
    *,
    series_id: str,
    label: str,
    fetch_result: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "series_id": series_id,
        "label": label,
        "value": fetch_result.get("value"),
        "observation_date": fetch_result.get("observation_date"),
    }
    if fetch_result.get("error"):
        body["error"] = fetch_result["error"]
        body["value"] = None
        body["observation_date"] = None
    return body


def build_pce_vs_target(api_key: str) -> tuple[dict[str, Any], bool]:
    """Fetch headline and core PCE YoY vs the Fed's 2% target.

    Returns ``(payload, all_network_failed)``. ``all_network_failed`` is true only
    when both series hit a network-level error (timeout/connection).
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    series_defs = (
        (PCE_HEADLINE_SERIES_ID, PCE_HEADLINE_LABEL, "headline"),
        (PCE_CORE_SERIES_ID, PCE_CORE_LABEL, "core"),
    )

    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(_fetch_fred_pc1_latest, api_key, sid): key
            for sid, _label, key in series_defs
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()

    network_failed = 0
    for _sid, _label, key in series_defs:
        err = results[key].get("error")
        if err and str(err).startswith(_NETWORK_ERROR_PREFIXES):
            network_failed += 1

    payload: dict[str, Any] = {
        "as_of": as_of,
        "target": FED_PCE_INFLATION_TARGET,
        "headline": _metric_payload(
            series_id=PCE_HEADLINE_SERIES_ID,
            label=PCE_HEADLINE_LABEL,
            fetch_result=results["headline"],
        ),
        "core": _metric_payload(
            series_id=PCE_CORE_SERIES_ID,
            label=PCE_CORE_LABEL,
            fetch_result=results["core"],
        ),
    }
    return payload, network_failed == len(series_defs)
