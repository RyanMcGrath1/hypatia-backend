"""Economy premium detail screens — ``GET /api/economy/detail`` (Expo ``economyDetailApi``)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from hypatia.services.economy.core import (
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
