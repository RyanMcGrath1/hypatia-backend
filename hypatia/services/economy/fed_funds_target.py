"""Fed funds target range — ``GET /api/economy/rates/fed-funds-target``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hypatia.services.economy.core import _build_fred_series_bundle

FED_FUNDS_TARGET_LOWER_ID = "DFEDTARL"
FED_FUNDS_TARGET_UPPER_ID = "DFEDTARU"

FED_FUNDS_TARGET_SERIES: tuple[tuple[str, str], ...] = (
    (FED_FUNDS_TARGET_LOWER_ID, "Federal Funds Target Range - Lower Limit"),
    (FED_FUNDS_TARGET_UPPER_ID, "Federal Funds Target Range - Upper Limit"),
)


def _parse_target_value(raw: Any) -> float | None:
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


def _latest_observation(
    series_list: list[dict[str, Any]],
    series_id: str,
) -> tuple[str, float] | None:
    for entry in series_list:
        if entry.get("id") != series_id:
            continue
        observations = entry.get("observations") or []
        if not isinstance(observations, list) or not observations:
            return None
        for row in reversed(observations):
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            if not d:
                continue
            value = _parse_target_value(row.get("value"))
            if value is not None:
                return d, value
        return None
    return None


def build_fed_funds_target(
    api_key: str,
    *,
    observation_start: str,
    observation_end: str,
) -> tuple[dict[str, Any], bool]:
    """Fetch FOMC fed funds target range (``DFEDTARL`` / ``DFEDTARU``) over an inclusive window.

    Returns ``(payload, all_network_failed)``. The payload includes ``series`` (same shape as
    ``labor/sector``), plus headline fields ``target_lower``, ``target_upper``, and
    ``observation_date`` when both bounds are available.
    """
    payload, all_network_failed = _build_fred_series_bundle(
        api_key,
        observation_start=observation_start,
        observation_end=observation_end,
        series_defs=FED_FUNDS_TARGET_SERIES,
    )

    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload["as_of"] = as_of

    lower = _latest_observation(payload["series"], FED_FUNDS_TARGET_LOWER_ID)
    upper = _latest_observation(payload["series"], FED_FUNDS_TARGET_UPPER_ID)
    if lower and upper:
        payload["target_lower"] = lower[1]
        payload["target_upper"] = upper[1]
        payload["observation_date"] = max(lower[0], upper[0])
    else:
        payload["target_lower"] = None
        payload["target_upper"] = None
        payload["observation_date"] = None

    return payload, all_network_failed
