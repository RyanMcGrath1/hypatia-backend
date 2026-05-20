"""Economy premium detail screens — ``GET /api/economy/detail`` (Expo ``economyDetailApi``)."""

from __future__ import annotations

from typing import Any

from hypatia.services.economy.core import (
    _overview_def_for_section,
    build_economy_overview_sector,
    resolve_sector_dashboard_observation_window,
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
