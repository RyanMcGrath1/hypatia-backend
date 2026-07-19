"""CPI component YoY breakdown — ``GET /api/economy/inflation/cpi-components``."""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from typing import Any

from hypatia.services.economy.pce_vs_target import (
    _NETWORK_ERROR_PREFIXES,
    _fetch_fred_pc1_latest,
)

CPI_HEADLINE_SERIES_ID = "CPIAUCSL"
CPI_HEADLINE_LABEL = "Headline CPI"

# (key, FRED series_id, display label, parent component keys when nested)
CPI_COMPONENT_DEFS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("shelter", "CUSR0000SAH1", "Shelter", ("core_services",)),
    ("food", "CPIUFDSL", "Food", ()),
    ("energy", "CPIENGSL", "Energy", ()),
    ("core_goods", "CUSR0000SACL1E", "Core Goods", ()),
    ("core_services", "CUSR0000SASLE", "Core Services", ()),
)


def _metric_delta(
    value: float | None,
    previous_value: float | None,
) -> float | None:
    if value is None or previous_value is None:
        return None
    return round(value - previous_value, 2)


def _metric_payload(
    *,
    series_id: str,
    label: str,
    fetch_result: dict[str, Any],
    key: str | None = None,
    includes_in: tuple[str, ...] = (),
) -> dict[str, Any]:
    value = fetch_result.get("value")
    previous_value = fetch_result.get("previous_value")
    body: dict[str, Any] = {
        "series_id": series_id,
        "label": label,
        "value": value,
        "observation_date": fetch_result.get("observation_date"),
        "previous_value": previous_value,
        "previous_observation_date": fetch_result.get("previous_observation_date"),
        "delta": _metric_delta(value, previous_value),
    }
    if key is not None:
        body["key"] = key
    if includes_in:
        body["includes_in"] = list(includes_in)
    if fetch_result.get("error"):
        body["error"] = fetch_result["error"]
        body["value"] = None
        body["observation_date"] = None
        body["previous_value"] = None
        body["previous_observation_date"] = None
        body["delta"] = None
    return body


def build_cpi_components(api_key: str) -> tuple[dict[str, Any], bool]:
    """Fetch headline CPI and component YoY rates (``units=pc1``).

    Returns ``(payload, all_network_failed)``. ``all_network_failed`` is true only
    when every FRED request hit a network-level error (timeout/connection).
    """
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fetch_targets: list[tuple[str, str]] = [("headline", CPI_HEADLINE_SERIES_ID)]
    fetch_targets.extend((key, series_id) for key, series_id, _label, _parents in CPI_COMPONENT_DEFS)

    results: dict[str, dict[str, Any]] = {}
    workers = max(1, len(fetch_targets))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _fetch_fred_pc1_latest,
                api_key,
                series_id,
            ): result_key
            for result_key, series_id in fetch_targets
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()

    network_failed = 0
    for result_key, _series_id in fetch_targets:
        err = results[result_key].get("error")
        if err and str(err).startswith(_NETWORK_ERROR_PREFIXES):
            network_failed += 1

    headline_result = results["headline"]
    components = [
        _metric_payload(
            key=key,
            series_id=series_id,
            label=label,
            fetch_result=results[key],
            includes_in=includes_in,
        )
        for key, series_id, label, includes_in in CPI_COMPONENT_DEFS
    ]

    observation_date = headline_result.get("observation_date")
    if not observation_date:
        for component in components:
            observation_date = component.get("observation_date")
            if observation_date:
                break

    payload: dict[str, Any] = {
        "as_of": as_of,
        "observation_date": observation_date,
        "headline": _metric_payload(
            series_id=CPI_HEADLINE_SERIES_ID,
            label=CPI_HEADLINE_LABEL,
            fetch_result=headline_result,
        ),
        "components": components,
    }
    return payload, network_failed == len(fetch_targets)
