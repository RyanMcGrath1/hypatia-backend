"""Economy premium detail screens — ``GET /api/economy/detail`` (Expo ``economyDetailApi``)."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

import requests

from hypatia.logging_config import log_upstream
from hypatia.services.economy.core import (
    FRED_OBSERVATIONS_URL,
    FRED_REQUEST_TIMEOUT,
    _overview_def_for_section,
    _sector_dashboard_clock_today,
    build_economy_overview_sector,
    fetch_fred_series,
    resolve_sector_dashboard_observation_window,
)

GDP_GROWTH_SERIES_ID = "A191RL1Q225SBEA"
GDP_GROWTH_LABEL = "Real GDP Growth Rate"
GDP_GROWTH_UNIT = (
    "percent change from preceding period, seasonally adjusted annual rate"
)

GDP_TOTAL_SERIES_ID = "GDPC1"
GDP_SECTOR_CONTRIBUTION_UNIT = "percent of real GDP"
GDP_SECTOR_CONTRIBUTION_FETCH_LIMIT = 1

# BEA real value added by industry (billions chained 2017 dollars, SAAR).
GDP_SECTOR_CONTRIBUTION_DEFS: tuple[tuple[str, str, str], ...] = (
    ("services", "RVASPI", "Services"),
    ("manufacturing", "RVAMA", "Manufacturing"),
    ("agriculture", "RVAAFH", "Agriculture"),
)

logger = logging.getLogger(__name__)

_NETWORK_ERROR_PREFIXES = (
    "FRED request timed out",
    "FRED request failed",
)

# Expo ``EconomyDetailTopic`` → overview ``section_key`` (same FRED bundles as sector dashboards).
_DETAIL_TOPIC_TO_SECTION: dict[str, str] = {
    "gdp": "gdp",
    "labor": "labor",
    "inflation": "inflation",
    "markets": "interest_rates",
}


def resolve_economy_detail_topic(topic: str) -> str | None:
    """Map ``topic`` query param to an overview section key, or ``None`` if unknown."""
    return _DETAIL_TOPIC_TO_SECTION.get(topic.strip().lower())


def resolve_gdp_growth_observation_window(
    q_start: str | None,
    q_end: str | None,
    *,
    today: date | None = None,
) -> tuple[str, str]:
    """Inclusive FRED window for ``GET /api/economy/gdp/growth-rate``.

    Defaults to roughly the last three calendar years (~12 quarterly points) when both
    bounds are omitted; otherwise uses the same rules as sector dashboards.
    """
    day = today if today is not None else _sector_dashboard_clock_today()

    def norm(x: str | None) -> str | None:
        if x is None:
            return None
        t = x.strip()
        return t or None

    s0, e0 = norm(q_start), norm(q_end)
    if s0 is None and e0 is None:
        start = date(day.year - 3, 1, 1)
        return start.isoformat(), day.isoformat()
    return resolve_sector_dashboard_observation_window(q_start, q_end, today=day)


def _numeric_observations(raw_obs: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in raw_obs:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        val = row.get("value")
        n: float | None
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            n = float(val)
        elif isinstance(val, str):
            t = val.strip()
            if not t or t == ".":
                continue
            try:
                n = float(t)
            except ValueError:
                continue
        else:
            continue
        if n == n:
            out.append({"date": d, "value": n})
    return out


def build_economy_detail(
    api_key: str,
    topic: str,
    *,
    observation_end: str | None = None,
) -> dict[str, Any]:
    """Build ``{ topic, charts, headline, as_of }`` for premium economy detail views."""
    section_key = resolve_economy_detail_topic(topic)
    if section_key is None:
        raise ValueError("Unknown economy detail topic")

    obs_start, obs_end = resolve_sector_dashboard_observation_window(
        None,
        observation_end,
    )
    sector_payload = build_economy_overview_sector(
        api_key,
        section_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    section = sector_payload["sections"][section_key]
    overview = _overview_def_for_section(section_key)

    chart_key = section_key
    observations = _numeric_observations(section.get("observations") or [])

    chart: dict[str, Any] = {
        "key": chart_key,
        "series_id": section.get("series_id") or (overview.series_id if overview else ""),
        "label": section.get("label") or (overview.label if overview else chart_key),
        "unit": section.get("unit") or (overview.unit if overview else ""),
        "observations": observations,
    }
    if section.get("error"):
        chart["error"] = section["error"]
        if section.get("hint"):
            chart["hint"] = section["hint"]

    headline: dict[str, Any] | None = None
    if observations and not section.get("error"):
        latest = observations[0]
        headline = {
            "chart_key": chart_key,
            "series_id": chart["series_id"],
            "label": chart["label"],
            "unit": chart["unit"],
            "value": latest["value"],
            "observation_date": latest["date"],
        }

    out: dict[str, Any] = {
        "as_of": sector_payload["as_of"],
        "topic": topic.strip().lower(),
        "charts": [chart],
        "headline": headline,
    }
    if observation_end:
        out["observation_end"] = observation_end
    elif sector_payload.get("observation_end"):
        out["observation_end"] = sector_payload["observation_end"]
    return out


def build_gdp_growth_rate(
    api_key: str,
    *,
    observation_start: str,
    observation_end: str,
) -> tuple[dict[str, Any], bool]:
    """Fetch Real GDP QoQ growth (``A191RL1Q225SBEA``) for the GDP detail widget.

    Returns ``(payload, network_failed)``. Observations are newest first.
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fetch_result = fetch_fred_series(
        GDP_GROWTH_SERIES_ID,
        observation_start,
        api_key,
        end_date=observation_end,
    )

    network_failed = False
    err = fetch_result.get("error")
    if err and str(err).startswith(_NETWORK_ERROR_PREFIXES):
        network_failed = True

    observations_asc = _numeric_observations(fetch_result.get("observations") or [])
    observations = list(reversed(observations_asc))

    payload: dict[str, Any] = {
        "as_of": as_of,
        "start_date": observation_start,
        "end_date": observation_end,
        "series_id": GDP_GROWTH_SERIES_ID,
        "label": GDP_GROWTH_LABEL,
        "unit": GDP_GROWTH_UNIT,
        "value": None,
        "observation_date": None,
        "observations": observations,
    }

    if err:
        payload["error"] = err
    elif observations:
        latest = observations[0]
        payload["value"] = round(latest["value"], 2)
        payload["observation_date"] = latest["date"]
    elif not err:
        payload["error"] = "No usable observations in FRED response"

    return payload, network_failed


def _parse_gdp_level_value(raw: Any) -> float | None:
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


def _fetch_fred_latest_level(api_key: str, series_id: str) -> dict[str, Any]:
    """Latest observation for one FRED level series (``sort_order=desc``, ``limit=1``)."""
    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(GDP_SECTOR_CONTRIBUTION_FETCH_LIMIT),
    }
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning("FRED GDP sector request timed out series_id=%s", series_id)
        return {"error": "FRED request timed out"}
    except requests.RequestException as exc:
        logger.warning(
            "FRED GDP sector request failed series_id=%s error=%s",
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
        value = _parse_gdp_level_value(row.get("value"))
        if value is None:
            continue
        return {"value": value, "observation_date": d}

    return {"error": "No usable observations in FRED response"}


def _gdp_sector_share_pct(sector_value: float, gdp_value: float) -> float | None:
    if gdp_value == 0:
        return None
    return round(sector_value / gdp_value * 100, 1)


def build_gdp_sector_contribution(api_key: str) -> tuple[dict[str, Any], bool]:
    """Latest real value-added share of GDP for services, manufacturing, and agriculture.

    Returns ``(payload, all_network_failed)``. Each sector's ``value`` is its share of
    ``GDPC1`` for the latest common BEA quarter (percent, one decimal).
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fetch_targets: list[tuple[str, str]] = [("gdp", GDP_TOTAL_SERIES_ID)]
    fetch_targets.extend((key, series_id) for key, series_id, _label in GDP_SECTOR_CONTRIBUTION_DEFS)

    results: dict[str, dict[str, Any]] = {}
    workers = max(1, len(fetch_targets))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_fred_latest_level, api_key, series_id): result_key
            for result_key, series_id in fetch_targets
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()

    network_failed = 0
    for result_key, _series_id in fetch_targets:
        err = results[result_key].get("error")
        if err and str(err).startswith(_NETWORK_ERROR_PREFIXES):
            network_failed += 1

    gdp_result = results["gdp"]
    gdp_value = gdp_result.get("value")
    gdp_date = gdp_result.get("observation_date")

    sectors: list[dict[str, Any]] = []
    observation_date: str | None = gdp_date if isinstance(gdp_date, str) else None

    for key, series_id, label in GDP_SECTOR_CONTRIBUTION_DEFS:
        fetch_result = results[key]
        sector_value = fetch_result.get("value")
        sector_date = fetch_result.get("observation_date")
        entry: dict[str, Any] = {
            "key": key,
            "series_id": series_id,
            "label": label,
            "value": None,
            "observation_date": sector_date if isinstance(sector_date, str) else None,
        }

        err = fetch_result.get("error")
        gdp_err = gdp_result.get("error")
        if err:
            entry["error"] = err
        elif gdp_err:
            entry["error"] = gdp_err
        elif isinstance(sector_value, (int, float)) and isinstance(gdp_value, (int, float)):
            share = _gdp_sector_share_pct(float(sector_value), float(gdp_value))
            if share is None:
                entry["error"] = "Unable to compute sector share of GDP"
            else:
                entry["value"] = share
                if isinstance(sector_date, str):
                    observation_date = sector_date
        else:
            entry["error"] = "No usable observations in FRED response"

        sectors.append(entry)

    payload: dict[str, Any] = {
        "as_of": as_of,
        "unit": GDP_SECTOR_CONTRIBUTION_UNIT,
        "gdp_series_id": GDP_TOTAL_SERIES_ID,
        "observation_date": observation_date,
        "sectors": sectors,
    }
    if gdp_err := gdp_result.get("error"):
        payload["error"] = gdp_err

    return payload, network_failed == len(fetch_targets)


GDP_GROWTH_HEADWINDS_FETCH_LIMIT = 2
FED_PCE_INFLATION_TARGET = 2.0

GDP_HEADWIND_SUPPLY_CHAIN_SERIES_ID = "FRGSHPUSM649NCIS"
GDP_HEADWIND_SUPPLY_CHAIN_UNITS = "pch"
GDP_HEADWIND_FED_LOWER_SERIES_ID = "DFEDTARL"
GDP_HEADWIND_FED_UPPER_SERIES_ID = "DFEDTARU"
GDP_HEADWIND_YIELD_CURVE_SERIES_ID = "T10Y2Y"
GDP_HEADWIND_INFLATION_SERIES_ID = "PCEPILFE"
GDP_HEADWIND_INFLATION_UNITS = "pc1"

_GDP_HEADWIND_FETCH_TARGETS: tuple[tuple[str, str, str | None], ...] = (
    ("supply_chain", GDP_HEADWIND_SUPPLY_CHAIN_SERIES_ID, GDP_HEADWIND_SUPPLY_CHAIN_UNITS),
    ("fed_lower", GDP_HEADWIND_FED_LOWER_SERIES_ID, None),
    ("fed_upper", GDP_HEADWIND_FED_UPPER_SERIES_ID, None),
    ("yield_curve", GDP_HEADWIND_YIELD_CURVE_SERIES_ID, None),
    ("inflation", GDP_HEADWIND_INFLATION_SERIES_ID, GDP_HEADWIND_INFLATION_UNITS),
)


def _headwind_risk_label(level: str) -> str:
    return {"high": "High Risk", "medium": "Medium Risk", "low": "Low Risk"}.get(
        level,
        "Medium Risk",
    )


def _freight_shipments_risk_level(mom_pct: float) -> str:
    """Risk from Cass freight shipment MoM % change (``units=pch``)."""
    if mom_pct <= -2.0:
        return "high"
    if mom_pct <= 0:
        return "medium"
    return "low"


def _fed_funds_risk_level(upper: float) -> str:
    if upper >= 5.0:
        return "high"
    if upper >= 3.5:
        return "medium"
    return "low"


def _yield_curve_risk_level(value: float) -> str:
    if value < 0:
        return "high"
    if value < 0.5:
        return "medium"
    return "low"


def _core_pce_risk_level(value: float) -> str:
    if value > 3.5:
        return "high"
    if value > 2.5:
        return "medium"
    return "low"


def _fetch_fred_recent_observations(
    api_key: str,
    series_id: str,
    *,
    limit: int = GDP_GROWTH_HEADWINDS_FETCH_LIMIT,
    units: str | None = None,
) -> dict[str, Any]:
    """Latest FRED observations for one series (newest first)."""
    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(limit),
    }
    if units:
        params["units"] = units

    t0 = time.perf_counter()
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning("FRED GDP headwind request timed out series_id=%s", series_id)
        return {"error": "FRED request timed out"}
    except requests.RequestException as exc:
        logger.warning(
            "FRED GDP headwind request failed series_id=%s error=%s",
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

    collected: list[tuple[str, float]] = []
    for row in raw_obs:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        value = _parse_gdp_level_value(row.get("value"))
        if value is None:
            continue
        collected.append((d, value))
        if len(collected) >= limit:
            break

    if not collected:
        return {"error": "No usable observations in FRED response"}

    out: dict[str, Any] = {
        "value": collected[0][1],
        "observation_date": collected[0][0],
    }
    if len(collected) > 1:
        out["previous_value"] = collected[1][1]
        out["previous_observation_date"] = collected[1][0]
    return out


def _supply_chain_headwind(fetch_result: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": "supply_chain",
        "series_id": GDP_HEADWIND_SUPPLY_CHAIN_SERIES_ID,
        "title": "Supply Chain",
        "value": None,
        "previous_value": None,
        "observation_date": None,
        "body": "",
        "risk": None,
        "risk_label": None,
    }
    err = fetch_result.get("error")
    if err:
        entry["error"] = err
        return entry

    value = fetch_result.get("value")
    if not isinstance(value, (int, float)):
        entry["error"] = "No usable observations in FRED response"
        return entry

    prev = fetch_result.get("previous_value")
    entry["value"] = round(float(value), 1)
    entry["observation_date"] = fetch_result.get("observation_date")
    if isinstance(prev, (int, float)):
        entry["previous_value"] = round(float(prev), 1)

    risk = _freight_shipments_risk_level(float(value))
    entry["risk"] = risk
    entry["risk_label"] = _headwind_risk_label(risk)
    if float(value) < 0:
        move = f"declined {abs(float(value)):.1f}%"
    elif float(value) > 0:
        move = f"rose {float(value):.1f}%"
    else:
        move = "were unchanged"
    if isinstance(prev, (int, float)):
        if float(prev) < 0:
            prev_phrase = f"{abs(float(prev)):.1f}% decline"
        elif float(prev) > 0:
            prev_phrase = f"{float(prev):.1f}% gain"
        else:
            prev_phrase = "flat reading"
        entry["body"] = (
            f"U.S. freight shipment volumes {move} month-over-month, "
            f"after a {prev_phrase} the prior month."
        )
    else:
        entry["body"] = f"U.S. freight shipment volumes {move} month-over-month."
    return entry


def _interest_rates_headwind(
    lower_result: dict[str, Any],
    upper_result: dict[str, Any],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": "interest_rates",
        "series_id": GDP_HEADWIND_FED_UPPER_SERIES_ID,
        "title": "Interest Rates",
        "value": None,
        "target_lower": None,
        "target_upper": None,
        "observation_date": None,
        "body": "",
        "risk": None,
        "risk_label": None,
    }
    lower_err = lower_result.get("error")
    upper_err = upper_result.get("error")
    if lower_err or upper_err:
        entry["error"] = lower_err or upper_err
        return entry

    lower = lower_result.get("value")
    upper = upper_result.get("value")
    if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
        entry["error"] = "No usable observations in FRED response"
        return entry

    entry["target_lower"] = round(float(lower), 2)
    entry["target_upper"] = round(float(upper), 2)
    entry["value"] = entry["target_upper"]
    lower_date = lower_result.get("observation_date")
    upper_date = upper_result.get("observation_date")
    if isinstance(lower_date, str) and isinstance(upper_date, str):
        entry["observation_date"] = max(lower_date, upper_date)
    elif isinstance(upper_date, str):
        entry["observation_date"] = upper_date
    elif isinstance(lower_date, str):
        entry["observation_date"] = lower_date

    risk = _fed_funds_risk_level(float(upper))
    entry["risk"] = risk
    entry["risk_label"] = _headwind_risk_label(risk)
    if float(lower) == float(upper):
        entry["body"] = f"Fed funds target is {float(upper):.2f}%."
    else:
        entry["body"] = (
            f"Fed funds target range is {float(lower):.2f}–{float(upper):.2f}%."
        )
    return entry


def _yield_curve_headwind(fetch_result: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": "yield_curve",
        "series_id": GDP_HEADWIND_YIELD_CURVE_SERIES_ID,
        "title": "Yield Curve",
        "value": None,
        "previous_value": None,
        "observation_date": None,
        "body": "",
        "risk": None,
        "risk_label": None,
    }
    err = fetch_result.get("error")
    if err:
        entry["error"] = err
        return entry

    value = fetch_result.get("value")
    if not isinstance(value, (int, float)):
        entry["error"] = "No usable observations in FRED response"
        return entry

    prev = fetch_result.get("previous_value")
    entry["value"] = round(float(value), 2)
    entry["observation_date"] = fetch_result.get("observation_date")
    if isinstance(prev, (int, float)):
        entry["previous_value"] = round(float(prev), 2)

    risk = _yield_curve_risk_level(float(value))
    entry["risk"] = risk
    entry["risk_label"] = _headwind_risk_label(risk)
    if float(value) < 0:
        curve = "Inverted"
    elif float(value) < 0.5:
        curve = "Flat"
    else:
        curve = "Positive"
    entry["body"] = f"10Y–2Y spread is {float(value):.2f}%. {curve} yield curve."
    return entry


def _inflation_headwind(fetch_result: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": "inflation",
        "series_id": GDP_HEADWIND_INFLATION_SERIES_ID,
        "title": "Inflation",
        "value": None,
        "previous_value": None,
        "observation_date": None,
        "body": "",
        "risk": None,
        "risk_label": None,
    }
    err = fetch_result.get("error")
    if err:
        entry["error"] = err
        return entry

    value = fetch_result.get("value")
    if not isinstance(value, (int, float)):
        entry["error"] = "No usable observations in FRED response"
        return entry

    prev = fetch_result.get("previous_value")
    entry["value"] = round(float(value), 1)
    entry["observation_date"] = fetch_result.get("observation_date")
    if isinstance(prev, (int, float)):
        entry["previous_value"] = round(float(prev), 1)

    risk = _core_pce_risk_level(float(value))
    entry["risk"] = risk
    entry["risk_label"] = _headwind_risk_label(risk)
    if float(value) > FED_PCE_INFLATION_TARGET:
        vs_target = "above"
    elif float(value) < FED_PCE_INFLATION_TARGET:
        vs_target = "below"
    else:
        vs_target = "at"
    body = (
        f"Core PCE inflation is {float(value):.1f}% YoY, {vs_target} the Fed's "
        f"{FED_PCE_INFLATION_TARGET:.0f}% target."
    )
    if isinstance(prev, (int, float)):
        delta = float(value) - float(prev)
        if abs(delta) >= 0.05:
            direction = "Up" if delta > 0 else "Down"
            body += f" {direction} from {float(prev):.1f}% last month."
    entry["body"] = body
    return entry


def build_gdp_growth_headwinds(api_key: str) -> tuple[dict[str, Any], bool]:
    """Latest macro headwinds for the GDP detail risks panel (four cards).

    Returns ``(payload, all_network_failed)``.
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    results: dict[str, dict[str, Any]] = {}
    workers = max(1, len(_GDP_HEADWIND_FETCH_TARGETS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _fetch_fred_recent_observations,
                api_key,
                series_id,
                units=units,
            ): result_key
            for result_key, series_id, units in _GDP_HEADWIND_FETCH_TARGETS
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()

    network_failed = 0
    for result_key, _series_id, _units in _GDP_HEADWIND_FETCH_TARGETS:
        err = results[result_key].get("error")
        if err and str(err).startswith(_NETWORK_ERROR_PREFIXES):
            network_failed += 1

    risks = [
        _supply_chain_headwind(results["supply_chain"]),
        _interest_rates_headwind(results["fed_lower"], results["fed_upper"]),
        _yield_curve_headwind(results["yield_curve"]),
        _inflation_headwind(results["inflation"]),
    ]

    return {"as_of": as_of, "risks": risks}, network_failed == len(
        _GDP_HEADWIND_FETCH_TARGETS
    )
