"""FRED-backed economy summary for GET /api/economy/summary."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# Upstream timeout per tile (seconds); aligned with civic proxy style in app.py
FRED_REQUEST_TIMEOUT = 30


@dataclass(frozen=True)
class EconomyTileDef:
    tile_id: str
    series_id: str
    label: str
    unit: str


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
        return (
            tile.tile_id,
            {
                "error": "FRED request timed out",
                "hint": f"series_id={tile.series_id}",
            },
        )
    except requests.RequestException as exc:
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
