"""FRED-backed economy aggregation for GET /api/economy/dashboard and related routes."""

from __future__ import annotations

import concurrent.futures
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

from hypatia.logging_config import log_upstream

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

# Sector dashboard: FRED row cap when querying an explicit observation window.
SECTOR_DASHBOARD_FRED_ROW_CAP = 2500


def _sector_dashboard_clock_today() -> date:
    """UTC calendar date for default sector dashboard window (tests may patch)."""
    return datetime.now(timezone.utc).date()


def resolve_sector_dashboard_observation_window(
    q_start: str | None,
    q_end: str | None,
    *,
    today: date | None = None,
) -> tuple[str, str]:
    """Inclusive FRED window for ``GET /api/economy/<sector>/dashboard``.

    Defaults to **year-to-date (UTC)**: ``{today.year}-01-01`` through ``today``.

    * Both omitted → YTD (UTC).
    * Only ``observation_start`` → that date … ``today`` (UTC).
    * Only ``observation_end`` → ``Jan 1`` of that date's year … ``observation_end``.
    """
    day = today if today is not None else _sector_dashboard_clock_today()

    def norm(x: str | None) -> str | None:
        if x is None:
            return None
        t = x.strip()
        return t or None

    s0, e0 = norm(q_start), norm(q_end)

    def parse_iso(label: str, raw: str) -> date:
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid {label}: use YYYY-MM-DD (e.g. 2025-11-01)",
            ) from exc

    if s0 is None and e0 is None:
        return f"{day.year}-01-01", day.isoformat()

    try:
        if s0 is not None and e0 is not None:
            ds, de = parse_iso("observation_start", s0), parse_iso("observation_end", e0)
            if ds > de:
                raise ValueError("observation_start must be <= observation_end")
            return ds.isoformat(), de.isoformat()
        if s0 is not None:
            ds = parse_iso("observation_start", s0)
            if ds > day:
                raise ValueError("observation_start cannot be after today (UTC)")
            return ds.isoformat(), day.isoformat()
        assert e0 is not None
        de = parse_iso("observation_end", e0)
        ds = date(de.year, 1, 1)
        if ds > de:
            raise ValueError("observation_start must be <= observation_end")
        return ds.isoformat(), de.isoformat()
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("Invalid ") or msg.startswith("observation_"):
            raise
        raise ValueError("Invalid observation_start or observation_end") from exc


def _observation_row_in_window(row_date: str, start: str, end: str) -> bool:
    d = row_date.strip()
    return start <= d <= end


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

# App tab uses short ids in ``GET /api/economy/{id}/dashboard``
# (see Hypatia ``SECTOR_ID_TO_OVERVIEW_KEY``).
_ECONOMY_DASHBOARD_SECTOR_ALIASES: dict[str, str] = {
    "consumer": "consumer_spending",
    "rates": "interest_rates",
}

_OVERVIEW_SECTION_KEYS: frozenset[str] = frozenset(d.section_key for d in OVERVIEW_SERIES)


def resolve_economy_dashboard_sector(path_segment: str) -> str | None:
    """Map URL segment (section key or app alias) to ``OVERVIEW_SERIES.section_key``."""
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


def _fetch_overview_series(
    api_key: str,
    overview: EconomyOverviewDef,
    *,
    observation_start: str | None = None,
    observation_end: str | None = None,
    window_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Return (section_key, payload with observations or error).

    Observations are the most recent releases per series (newest first).

    ``window_mode`` (sector dashboards): FRED is called with ``observation_start`` and
    ``observation_end`` and **all** points in that inclusive window are returned (capped by
    :data:`SECTOR_DASHBOARD_FRED_ROW_CAP`). Otherwise the compact overview path returns the
    latest :data:`OVERVIEW_RECENT_OBSERVATIONS` rows (inflation uses an extended fetch).
    """
    if window_mode:
        if not observation_start or not observation_end:
            raise ValueError("window_mode requires observation_start and observation_end")
        fred_cap = SECTOR_DASHBOARD_FRED_ROW_CAP
    elif overview.section_key == OVERVIEW_INFLATION_SECTION_KEY:
        fred_cap = OVERVIEW_INFLATION_FRED_LIMIT
    else:
        fred_cap = OVERVIEW_RECENT_OBSERVATIONS

    params: dict[str, str] = {
        "series_id": overview.series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(fred_cap),
    }
    if window_mode:
        params["observation_start"] = observation_start
        params["observation_end"] = observation_end
    elif observation_end:
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
        if len(parsed_all) >= fred_cap:
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

    if window_mode:
        assert observation_start is not None and observation_end is not None
        parsed_all = [
            o
            for o in parsed_all
            if _observation_row_in_window(
                str(o.get("date", "")), observation_start, observation_end
            )
        ]
        out_obs = parsed_all
    else:
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
    observation_start: str,
    observation_end: str,
) -> dict[str, Any]:
    """Single-sector dashboard slice for an inclusive FRED observation window (sector routes)."""
    overview = _overview_def_for_section(section_key)
    if overview is None:
        raise ValueError(f"Unknown economy overview section_key: {section_key!r}")

    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _sk, body = _fetch_overview_series(
        api_key,
        overview,
        observation_start=observation_start,
        observation_end=observation_end,
        window_mode=True,
    )
    return {
        "as_of": as_of,
        "sections": {section_key: body},
        "observation_start": observation_start,
        "observation_end": observation_end,
    }


# ---------------------------------------------------------------------------
# Labor employment-by-sector endpoint (GET /api/economy/labor/sector)
# ---------------------------------------------------------------------------

# FRED ``US*`` / ``PAYEMS`` / ``MANEMP`` ids (seasonally adjusted, thousands of persons).
# ``CES*0000000001`` codes are BLS-style but are not valid ``series_id`` values on FRED.
EMPLOYMENT_SECTOR_SERIES: tuple[tuple[str, str], ...] = (
    ("PAYEMS", "Total Nonfarm Payrolls"),
    ("USPBS", "Professional & Business Services"),
    ("USEHS", "Education & Health Services"),
    ("USLAH", "Leisure & Hospitality"),
    ("USTRADE", "Retail Trade"),
    ("MANEMP", "Manufacturing"),
    ("USFIRE", "Financial Activities"),
    ("USCONS", "Construction"),
    ("USINFO", "Information Sector"),
)

_EMPLOYMENT_NETWORK_ERROR_PREFIXES = (
    "FRED request timed out",
    "FRED request failed",
)


def _clean_employment_value(raw: Any) -> str | None:
    """FRED uses ``"."`` (and occasionally empty strings) for missing values."""
    if not isinstance(raw, str):
        return None if raw is None else str(raw)
    s = raw.strip()
    if not s or s == ".":
        return None
    return s


def fetch_fred_series(
    series_id: str,
    start_date: str,
    api_key: str,
    *,
    end_date: str | None = None,
) -> dict[str, Any]:
    """GET FRED ``series/observations`` for one series over an inclusive date window.

    Returns ``{"observations": [{"date": str, "value": str | None}, ...]}`` on success
    (raw FRED values preserved as strings; ``"."`` → ``None``). On any failure returns
    ``{"observations": [], "error": "<message>"}`` and never raises.
    """
    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "asc",
    }
    if end_date:
        params["observation_end"] = end_date
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params=params,
            timeout=FRED_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning("FRED sector request timed out series_id=%s", series_id)
        return {"observations": [], "error": "FRED request timed out"}
    except requests.RequestException as exc:
        logger.warning("FRED sector request failed series_id=%s error=%s", series_id, exc)
        return {"observations": [], "error": f"FRED request failed: {exc!s}"}

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
        return {"observations": [], "error": err_msg}

    try:
        payload = resp.json()
    except ValueError:
        return {"observations": [], "error": "Invalid JSON from FRED"}

    raw_obs = payload.get("observations")
    if not isinstance(raw_obs, list):
        return {"observations": [], "error": "No observations in FRED response"}

    cleaned: list[dict[str, Any]] = []
    for row in raw_obs:
        if not isinstance(row, dict):
            continue
        d = row.get("date")
        if not isinstance(d, str):
            continue
        cleaned.append({"date": d, "value": _clean_employment_value(row.get("value"))})
    return {"observations": cleaned}


def build_employment_sectors(
    api_key: str,
    *,
    observation_start: str,
    observation_end: str,
) -> tuple[dict[str, Any], bool]:
    """Parallel fetch of the configured employment sectors over an inclusive FRED window.

    Returns ``(payload, all_network_failed)``. ``payload`` matches the documented schema;
    ``all_network_failed`` is true only when **every** series failed with a network-level
    exception (timeout/connection), which the caller surfaces as ``503``.
    """
    start_date, end_date = observation_start, observation_end

    results: dict[str, dict[str, Any]] = {}
    workers = max(1, len(EMPLOYMENT_SECTOR_SERIES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                fetch_fred_series,
                sid,
                start_date,
                api_key,
                end_date=end_date,
            ): sid
            for sid, _name in EMPLOYMENT_SECTOR_SERIES
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()

    sectors: dict[str, Any] = {}
    series_list: list[dict[str, Any]] = []
    network_failed = 0

    for sid, name in EMPLOYMENT_SECTOR_SERIES:
        body = results[sid]
        raw_observations = body.get("observations") or []
        observations = [
            obs
            for obs in raw_observations
            if isinstance(obs, dict)
            and _observation_row_in_window(str(obs.get("date", "")), start_date, end_date)
        ]
        err = body.get("error")

        sector_entry: dict[str, Any] = {"name": name, "observations": observations}
        series_entry: dict[str, Any] = {
            "id": sid,
            "name": name,
            "points": [[obs["date"], obs["value"]] for obs in observations],
        }
        if err:
            sector_entry["error"] = err
            series_entry["error"] = err
            if err.startswith(_EMPLOYMENT_NETWORK_ERROR_PREFIXES):
                network_failed += 1
        sectors[sid] = sector_entry
        series_list.append(series_entry)

    payload = {
        "start_date": start_date,
        "end_date": end_date,
        "sectors": sectors,
        "series": series_list,
    }
    return payload, network_failed == len(EMPLOYMENT_SECTOR_SERIES)
