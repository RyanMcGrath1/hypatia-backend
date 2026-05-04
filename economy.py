"""FRED-backed economy summary for GET /api/economy/summary and overview aggregation."""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# Upstream timeout per tile (seconds); aligned with civic proxy style in app.py
FRED_REQUEST_TIMEOUT = 30


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


def _first_day_of_quarter(year: int, quarter: int) -> date:
    month = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
    return date(year, month, 1)


def _last_day_of_quarter(year: int, quarter: int) -> date:
    if quarter == 1:
        return date(year, 3, 31)
    if quarter == 2:
        return date(year, 6, 30)
    if quarter == 3:
        return date(year, 9, 30)
    return date(year, 12, 31)


def _last_completed_quarter(today: date) -> tuple[int, int]:
    """Most recent calendar quarter whose last day is strictly before `today`."""
    y = today.year
    current_q = (today.month - 1) // 3 + 1
    for q in range(current_q - 1, 0, -1):
        if _last_day_of_quarter(y, q) < today:
            return (y, q)
    for q in range(4, 0, -1):
        if _last_day_of_quarter(y - 1, q) < today:
            return (y - 1, q)
    raise RuntimeError("could not determine last completed quarter")


def _quarter_before(year: int, quarter: int) -> tuple[int, int]:
    if quarter == 1:
        return year - 1, 4
    return year, quarter - 1


def last_two_full_quarters_window(ref: date) -> dict[str, Any]:
    """Inclusive date bounds covering exactly the last two completed calendar quarters."""
    y_new, q_new = _last_completed_quarter(ref)
    y_old, q_old = _quarter_before(y_new, q_new)
    start = _first_day_of_quarter(y_old, q_old)
    end = _last_day_of_quarter(y_new, q_new)

    def _qlabel(year: int, q: int) -> str:
        return f"{year}-Q{q}"

    return {
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
        "quarters": [_qlabel(y_old, q_old), _qlabel(y_new, q_new)],
        "label": f"{_qlabel(y_old, q_old)} – {_qlabel(y_new, q_new)}",
    }


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
            if (
                isinstance(value, (int, float))
                and isinstance(prior_val, (int, float))
            ):
                out["change"] = round(float(value) - float(prior_val), 6)

    return tile.tile_id, out


def _fetch_overview_series(
    api_key: str,
    overview: EconomyOverviewDef,
    observation_start: str,
    observation_end: str,
) -> tuple[str, dict[str, Any]]:
    """Return (section_key, payload with observations or error)."""
    params = {
        "series_id": overview.series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "observation_start": observation_start,
        "observation_end": observation_end,
        "limit": "100",
    }
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

    out_obs: list[dict[str, Any]] = []
    for row in observations:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        raw_v = str(row.get("value", "")).strip()
        out_obs.append(
            {
                "date": d,
                "value": _parse_observation_value(raw_v),
            }
        )

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
    return overview.section_key, body


def build_economy_summary(api_key: str) -> dict[str, Any]:
    """Build summary dict: as_of (ISO UTC), tiles keyed by tile_id."""
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tiles: dict[str, Any] = {}

    max_workers = max(1, len(ECONOMY_TILES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_fetch_single_tile, api_key, tile) for tile in ECONOMY_TILES
        ]
        for fut in concurrent.futures.as_completed(futures):
            tile_id, body = fut.result()
            tiles[tile_id] = body

    return {"as_of": as_of, "tiles": tiles}


def build_economy_overview(
    api_key: str,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """FRED observations for each overview series within the last two full quarters.

    `reference_date` is for tests; defaults to today's local calendar date.
    """
    ref = reference_date or date.today()
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    window = last_two_full_quarters_window(ref)
    observation_start = window["observation_start"]
    observation_end = window["observation_end"]

    sections: dict[str, Any] = {}
    max_workers = max(1, len(OVERVIEW_SERIES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _fetch_overview_series,
                api_key,
                series,
                observation_start,
                observation_end,
            )
            for series in OVERVIEW_SERIES
        ]
        for fut in concurrent.futures.as_completed(futures):
            section_key, body = fut.result()
            sections[section_key] = body

    return {
        "as_of": as_of,
        "window": window,
        "sections": sections,
    }
