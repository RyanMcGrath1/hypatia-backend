"""FRED-backed economy summary for GET /api/economy/summary and dashboard aggregation."""

from __future__ import annotations

import concurrent.futures
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# Upstream timeout per tile (seconds); aligned with civic proxy style in app.py
FRED_REQUEST_TIMEOUT = 30

# Overview: ten most recent FRED observations per series (quarterly vs monthly, etc.)
OVERVIEW_RECENT_OBSERVATIONS = 10

# CPI overview needs extra history for YoY on each displayed month. Buffer beyond
# (display + 12) absorbs duplicate observation dates (revisions) so calendar lookups
# still resolve t-1 / t-12 months.
OVERVIEW_INFLATION_SECTION_KEY = "inflation"
OVERVIEW_INFLATION_FRED_LIMIT = OVERVIEW_RECENT_OBSERVATIONS + 12 + 26


@dataclass(frozen=True)
class EconomyTileDef:
    tile_id: str
    series_id: str
    label: str
    unit: str


@dataclass(frozen=True)
class EconomyOverviewDef:
    section_key: str
    series_id: str
    label: str
    unit: str


OVERVIEW_SERIES: tuple[EconomyOverviewDef, ...] = (
    EconomyOverviewDef(
        section_key="gdp",
        series_id="GDPC1",
        label="Real Gross Domestic Product",
        unit="billions of chained 2017 dollars",
    ),
    EconomyOverviewDef(
        section_key="consumer_spending",
        series_id="PCE",
        label="Personal Consumption Expenditures",
        unit="billions of dollars",
    ),
    EconomyOverviewDef(
        section_key="labor",
        series_id="UNRATE",
        label="Unemployment Rate",
        unit="percent",
    ),
    EconomyOverviewDef(
        section_key="interest_rates",
        series_id="FEDFUNDS",
        label="Federal Funds Effective Rate",
        unit="percent",
    ),
    EconomyOverviewDef(
        section_key="inflation",
        series_id="CPIAUCSL",
        label="Consumer Price Index for All Urban Consumers: All Items",
        unit="index",
    ),
    EconomyOverviewDef(
        section_key="housing",
        series_id="CSUSHPISA",
        label="S&P/Case-Shiller U.S. National Home Price Index",
        unit="index",
    ),
)

# App tab uses short ids in ``GET /api/economy/{id}/dashboard`` (see Hypatia ``SECTOR_ID_TO_OVERVIEW_KEY``).
_ECONOMY_DASHBOARD_SECTOR_ALIASES: dict[str, str] = {
    "consumer": "consumer_spending",
    "rates": "interest_rates",
}

_OVERVIEW_SECTION_KEYS: frozenset[str] = frozenset(d.section_key for d in OVERVIEW_SERIES)


def resolve_economy_dashboard_sector(path_segment: str) -> str | None:
    """Map URL segment (canonical ``section_key`` or app sector id) to ``OVERVIEW_SERIES.section_key``."""
    key = path_segment.strip().lower()
    if not key:
        return None
    if key in _OVERVIEW_SECTION_KEYS:
        return key
    return _ECONOMY_DASHBOARD_SECTOR_ALIASES.get(key)


def _overview_def_for_section(section_key: str) -> EconomyOverviewDef | None:
    for d in OVERVIEW_SERIES:
        if d.section_key == section_key:
            return d
    return None


ECONOMY_TILES: tuple[EconomyTileDef, ...] = (
    EconomyTileDef(
        tile_id="cpi_all_items",
        series_id="CPIAUCSL",
        label="Consumer Price Index for All Urban Consumers: All Items",
        unit="index",
    ),
    EconomyTileDef(
        tile_id="unemployment_rate",
        series_id="UNRATE",
        label="Unemployment Rate",
        unit="percent",
    ),
    EconomyTileDef(
        tile_id="federal_funds_effective",
        series_id="FEDFUNDS",
        label="Federal Funds Effective Rate",
        unit="percent",
    ),
)


def _parse_observation_value(raw: str) -> int | float | str:
    """FRED uses '.' for missing; otherwise numeric strings."""
    s = raw.strip()
    if s == ".":
        return s
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _cpi_numeric_level(value: Any) -> float | None:
    if isinstance(value, (int, float)):  # noqa: UP038
        return float(value)
    return None


def _inflation_pct_change(current: float, base: float) -> float | None:
    if base == 0:
        return None
    return round((current - base) / base * 100, 2)


def _fred_observation_calendar_date(raw: str) -> date | None:
    """Parse FRED observation_date (typically YYYY-MM-DD)."""
    s = raw.strip()
    if len(s) < 10:
        return None
    try:
        y = int(s[0:4])
        m = int(s[5:7])
        d = int(s[8:10])
        return date(y, m, d)
    except ValueError:
        return None


def _cpi_month_key(raw_date: str) -> date | None:
    """First-of-month key so CPI periods align even if FRED uses varying month days."""
    d = _fred_observation_calendar_date(raw_date)
    if d is None:
        return None
    return date(d.year, d.month, 1)


def _calendar_month_add(month_start: date, delta_months: int) -> date:
    idx = month_start.year * 12 + (month_start.month - 1) + delta_months
    y, m0 = divmod(idx, 12)
    return date(y, m0 + 1, 1)


def _cpi_levels_by_month(parsed_desc_newest_first: list[dict[str, Any]]) -> dict[date, float]:
    """Map calendar month → level; first row wins (newest realtime when sorted desc)."""
    out: dict[date, float] = {}
    for o in parsed_desc_newest_first:
        mk = _cpi_month_key(str(o.get("date", "")))
        if mk is None:
            continue
        lvl = _cpi_numeric_level(o.get("value"))
        if lvl is None:
            continue
        out.setdefault(mk, lvl)
    return out


def _inflation_mom_for_month(levels: dict[date, float], month_key: date) -> float | None:
    prior_m = _calendar_month_add(month_key, -1)
    cur, prev = levels.get(month_key), levels.get(prior_m)
    if cur is None or prev is None:
        return None
    return _inflation_pct_change(cur, prev)


def _inflation_yoy_for_month(levels: dict[date, float], month_key: date) -> float | None:
    yago_m = _calendar_month_add(month_key, -12)
    cur, prior_y = levels.get(month_key), levels.get(yago_m)
    if cur is None or prior_y is None:
        return None
    return _inflation_pct_change(cur, prior_y)


def _row_index_for_cpi_month(
    parsed_desc_newest_first: list[dict[str, Any]],
    month_key: date,
) -> int | None:
    """First list index for month_key (newest realtime wins when sorted desc)."""
    for i, o in enumerate(parsed_desc_newest_first):
        mk = _cpi_month_key(str(o.get("date", "")))
        if mk == month_key:
            return i
    return None


def _inflation_mom_adjacent_rows(
    parsed_desc_newest_first: list[dict[str, Any]],
    row_index: int,
) -> float | None:
    """MoM using this row vs next older row with a usable numeric level (skips ``.`` gaps)."""
    if row_index >= len(parsed_desc_newest_first):
        return None
    cur = _cpi_numeric_level(parsed_desc_newest_first[row_index].get("value"))
    if cur is None:
        return None
    j = row_index + 1
    while j < len(parsed_desc_newest_first):
        prev = _cpi_numeric_level(parsed_desc_newest_first[j].get("value"))
        if prev is not None:
            return _inflation_pct_change(cur, prev)
        j += 1
    return None


def _inflation_mom_for_acceleration(
    levels: dict[date, float],
    parsed_desc_newest_first: list[dict[str, Any]],
    month_key: date,
) -> float | None:
    """Prefer calendar MoM; else adjacent-row MoM (needs newer → older numeric levels)."""
    cal = _inflation_mom_for_month(levels, month_key)
    if cal is not None:
        return cal
    idx = _row_index_for_cpi_month(parsed_desc_newest_first, month_key)
    if idx is None:
        return None
    return _inflation_mom_adjacent_rows(parsed_desc_newest_first, idx)


def _inflation_acceleration(mom_current: float | None, mom_prior_month: float | None) -> str | None:
    if mom_current is None or mom_prior_month is None:
        return None
    if math.isclose(mom_current, mom_prior_month, rel_tol=0.0, abs_tol=5e-3):
        return "flat"
    if mom_current > mom_prior_month:
        return "accelerating"
    return "decelerating"


def _attach_inflation_derived_fields(
    observations_display: list[dict[str, Any]],
    parsed_desc_newest_first: list[dict[str, Any]],
) -> None:
    """Add momInflation, yoyInflation (calendar), acceleration (calendar MoM with row fallback)."""
    levels = _cpi_levels_by_month(parsed_desc_newest_first)

    for obs in observations_display:
        mk = _cpi_month_key(str(obs.get("date", "")))
        if mk is None:
            obs["momInflation"] = None
            obs["yoyInflation"] = None
            obs["acceleration"] = None
            continue

        mom_i = _inflation_mom_for_month(levels, mk)
        yoy_i = _inflation_yoy_for_month(levels, mk)
        prior_m = _calendar_month_add(mk, -1)
        mom_accel = _inflation_mom_for_acceleration(levels, parsed_desc_newest_first, mk)
        mom_accel_prior = _inflation_mom_for_acceleration(levels, parsed_desc_newest_first, prior_m)

        obs["momInflation"] = mom_i
        obs["yoyInflation"] = yoy_i
        obs["acceleration"] = _inflation_acceleration(mom_accel, mom_accel_prior)


def _fetch_single_tile(api_key: str, tile: EconomyTileDef) -> tuple[str, dict[str, Any]]:
    """Return (tile_id, success_payload or error_payload)."""
    params = {
        "series_id": tile.series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": "2",
    }
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning(
            "FRED request timed out tile_id=%s series_id=%s",
            tile.tile_id,
            tile.series_id,
        )
        return (
            tile.tile_id,
            {
                "error": "FRED request timed out",
                "hint": f"series_id={tile.series_id}",
            },
        )
    except requests.RequestException as exc:
        logger.warning(
            "FRED request failed tile_id=%s series_id=%s error=%s",
            tile.tile_id,
            tile.series_id,
            exc,
        )
        return (
            tile.tile_id,
            {
                "error": "FRED request failed",
                "hint": f"series_id={tile.series_id}: {exc!s}",
            },
        )

    if not resp.ok:
        return (
            tile.tile_id,
            {
                "error": f"FRED returned HTTP {resp.status_code}",
                "hint": f"series_id={tile.series_id}",
            },
        )

    try:
        payload = resp.json()
    except ValueError:
        return (
            tile.tile_id,
            {
                "error": "Invalid JSON from FRED",
                "hint": f"series_id={tile.series_id}",
            },
        )

    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        return (
            tile.tile_id,
            {
                "error": "No observations in FRED response",
                "hint": f"series_id={tile.series_id}",
            },
        )

    latest = observations[0]
    if not isinstance(latest, dict):
        return (
            tile.tile_id,
            {
                "error": "Malformed FRED observations",
                "hint": f"series_id={tile.series_id}",
            },
        )

    latest_date = str(latest.get("date", "")).strip()
    latest_raw = str(latest.get("value", "")).strip()
    value = _parse_observation_value(latest_raw)

    out: dict[str, Any] = {
        "label": tile.label,
        "series_id": tile.series_id,
        "unit": tile.unit,
        "value": value,
        "observation_date": latest_date,
    }

    if len(observations) > 1:
        prior = observations[1]
        if isinstance(prior, dict):
            prior_raw = str(prior.get("value", "")).strip()
            prior_date = str(prior.get("date", "")).strip()
            prior_val = _parse_observation_value(prior_raw)
            out["prior_observation_date"] = prior_date
            if isinstance(value, (int, float)) and isinstance(  # noqa: UP038
                prior_val, (int, float)
            ):
                out["change"] = round(float(value) - float(prior_val), 6)

    return tile.tile_id, out


def _fetch_overview_series(
    api_key: str,
    overview: EconomyOverviewDef,
    *,
    observation_end: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (section_key, payload with observations or error).

    Observations are the most recent releases per series (newest first).
    """
    fetch_limit = (
        OVERVIEW_INFLATION_FRED_LIMIT
        if overview.section_key == OVERVIEW_INFLATION_SECTION_KEY
        else OVERVIEW_RECENT_OBSERVATIONS
    )
    params: dict[str, str] = {
        "series_id": overview.series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(fetch_limit),
    }
    if observation_end:
        params["observation_end"] = observation_end
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning(
            "FRED overview request timed out section=%s series_id=%s",
            overview.section_key,
            overview.series_id,
        )
        return (
            overview.section_key,
            {
                "error": "FRED request timed out",
                "hint": f"series_id={overview.series_id}",
            },
        )
    except requests.RequestException as exc:
        logger.warning(
            "FRED overview request failed section=%s series_id=%s error=%s",
            overview.section_key,
            overview.series_id,
            exc,
        )
        return (
            overview.section_key,
            {
                "error": "FRED request failed",
                "hint": f"series_id={overview.series_id}: {exc!s}",
            },
        )

    if not resp.ok:
        return (
            overview.section_key,
            {
                "error": f"FRED returned HTTP {resp.status_code}",
                "hint": f"series_id={overview.series_id}",
            },
        )

    try:
        payload = resp.json()
    except ValueError:
        return (
            overview.section_key,
            {
                "error": "Invalid JSON from FRED",
                "hint": f"series_id={overview.series_id}",
            },
        )

    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        return (
            overview.section_key,
            {
                "error": "No observations in FRED response",
                "hint": f"series_id={overview.series_id}",
            },
        )

    parsed_all: list[dict[str, Any]] = []
    for row in observations:
        if len(parsed_all) >= fetch_limit:
            break
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        raw_v = str(row.get("value", "")).strip()
        parsed_all.append(
            {
                "date": d,
                "value": _parse_observation_value(raw_v),
            }
        )

    out_obs = parsed_all[:OVERVIEW_RECENT_OBSERVATIONS]

    if not out_obs:
        return (
            overview.section_key,
            {
                "error": "No usable observations in FRED response",
                "hint": f"series_id={overview.series_id}",
            },
        )

    body: dict[str, Any] = {
        "label": overview.label,
        "series_id": overview.series_id,
        "unit": overview.unit,
        "observations": out_obs,
    }
    if overview.section_key == OVERVIEW_INFLATION_SECTION_KEY:
        _attach_inflation_derived_fields(out_obs, parsed_all)
        head = out_obs[0]
        body["momInflation"] = head.get("momInflation")
        body["yoyInflation"] = head.get("yoyInflation")
        body["acceleration"] = head.get("acceleration")

    return overview.section_key, body


def build_economy_summary(api_key: str) -> dict[str, Any]:
    """Build summary dict: as_of (ISO UTC), tiles keyed by tile_id."""
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tiles: dict[str, Any] = {}

    max_workers = max(1, len(ECONOMY_TILES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_fetch_single_tile, api_key, tile) for tile in ECONOMY_TILES]
        for fut in concurrent.futures.as_completed(futures):
            tile_id, body = fut.result()
            tiles[tile_id] = body

    return {"as_of": as_of, "tiles": tiles}


def build_economy_overview(
    api_key: str,
    *,
    observation_end: str | None = None,
) -> dict[str, Any]:
    """Recent FRED observations per overview series (newest first in each list).

    ``observation_end`` (YYYY-MM-DD) is forwarded to FRED so all sections share the same
    vintage window—useful to reproduce CPI enrichment against a known report month.
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    sections: dict[str, Any] = {}
    max_workers = max(1, len(OVERVIEW_SERIES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _fetch_overview_series,
                api_key,
                series,
                observation_end=observation_end,
            )
            for series in OVERVIEW_SERIES
        ]
        for fut in concurrent.futures.as_completed(futures):
            section_key, body = fut.result()
            sections[section_key] = body

    out: dict[str, Any] = {"as_of": as_of, "sections": sections}
    if observation_end:
        out["observation_end"] = observation_end
    return out


def build_economy_overview_sector(
    api_key: str,
    section_key: str,
    *,
    observation_end: str | None = None,
) -> dict[str, Any]:
    """Single-section dashboard slice: same shape as :func:`build_economy_overview` with one ``sections`` entry."""
    overview = _overview_def_for_section(section_key)
    if overview is None:
        raise ValueError(f"Unknown economy overview section_key: {section_key!r}")

    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _sk, body = _fetch_overview_series(
        api_key,
        overview,
        observation_end=observation_end,
    )
    out: dict[str, Any] = {"as_of": as_of, "sections": {section_key: body}}
    if observation_end:
        out["observation_end"] = observation_end
    return out
