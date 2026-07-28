"""Labor force metrics by age — ``GET /api/economy/labor/age-metrics``."""

from __future__ import annotations

from typing import Any

from hypatia.models import LaborAgeGroup, LaborAgeMetricId
from hypatia.services.economy.core import _build_fred_series_bundle

_AGE_GROUPS: tuple[str, ...] = tuple(g.value for g in LaborAgeGroup)

# metric_id → (display name, age_group → FRED series_id)
_LABOR_AGE_METRIC_DEFINITIONS: dict[str, tuple[str, dict[str, str]]] = {
    LaborAgeMetricId.UNEMPLOYMENT_RATE.value: (
        "Unemployment Rate",
        {
            LaborAgeGroup.AGE_16_19.value: "LNS14000012",
            LaborAgeGroup.AGE_20_24.value: "LNS14000036",
            LaborAgeGroup.AGE_25_54.value: "LNS14000060",
            LaborAgeGroup.AGE_55_PLUS.value: "LNS14024230",
        },
    ),
    LaborAgeMetricId.LABOR_FORCE_PARTICIPATION.value: (
        "Labor Force Participation Rate",
        {
            LaborAgeGroup.AGE_16_19.value: "LNS11300012",
            LaborAgeGroup.AGE_20_24.value: "LNS11300036",
            LaborAgeGroup.AGE_25_54.value: "LNS11300060",
            LaborAgeGroup.AGE_55_PLUS.value: "LNS11324230",
        },
    ),
}

# BLS ratio series id, or (ratio id, employment level id, population level id) when FRED
# does not publish the ratio (LNS12300036, LNS12324230) but does publish the levels.
_EMP_POP_BY_AGE: dict[str, str | tuple[str, str, str]] = {
    LaborAgeGroup.AGE_16_19.value: "LNS12300012",
    LaborAgeGroup.AGE_20_24.value: ("LNS12300036", "LNS12000036", "LNU00000036"),
    LaborAgeGroup.AGE_25_54.value: "LNS12300060",
    LaborAgeGroup.AGE_55_PLUS.value: ("LNS12324230", "LNS12024230", "LNU00024230"),
}

# Stable metric order in API responses.
LABOR_AGE_METRIC_IDS: tuple[str, ...] = tuple(m.value for m in LaborAgeMetricId)


def _flat_series_defs() -> tuple[tuple[str, str], ...]:
    """``(fred_series_id, internal label)`` for parallel FRED fetch."""
    out: list[tuple[str, str]] = []
    for metric_id in (
        LaborAgeMetricId.UNEMPLOYMENT_RATE.value,
        LaborAgeMetricId.LABOR_FORCE_PARTICIPATION.value,
    ):
        metric_name, by_age = _LABOR_AGE_METRIC_DEFINITIONS[metric_id]
        for age_group in _AGE_GROUPS:
            sid = by_age[age_group]
            out.append((sid, f"{metric_name}, {age_group}"))
    for age_group in _AGE_GROUPS:
        source = _EMP_POP_BY_AGE[age_group]
        if isinstance(source, str):
            out.append((source, f"Employment-Population Ratio, {age_group}"))
        else:
            ratio_id, emp_id, pop_id = source
            out.append((emp_id, f"Employment-Population Ratio, {age_group} (employment)"))
            out.append((pop_id, f"Employment-Population Ratio, {age_group} (population)"))
    return tuple(out)


def _observation_value_as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _emp_pop_ratio_from_levels(
    employment: list[dict[str, Any]],
    population: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """``100 * employment / population`` aligned by date (BLS employment-population ratio)."""
    pop_by_date: dict[str, float] = {}
    for row in population:
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        if not isinstance(date, str):
            continue
        pop_val = _observation_value_as_float(row.get("value"))
        if pop_val is not None and pop_val > 0:
            pop_by_date[date] = pop_val

    observations: list[dict[str, Any]] = []
    for row in employment:
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        if not isinstance(date, str):
            continue
        emp_val = _observation_value_as_float(row.get("value"))
        pop_val = pop_by_date.get(date)
        if emp_val is None or pop_val is None:
            observations.append({"date": date, "value": None})
            continue
        observations.append({"date": date, "value": str(round(100.0 * emp_val / pop_val, 1))})
    return observations


def _emp_pop_series_entry(
    age_group: str,
    by_fred_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = _EMP_POP_BY_AGE[age_group]
    if isinstance(source, str):
        ratio_id = source
        raw = by_fred_id.get(ratio_id, {"id": ratio_id, "observations": [], "error": "Missing series"})
        entry: dict[str, Any] = {
            "id": ratio_id,
            "age_group": age_group,
            "observations": raw.get("observations") or [],
        }
        if raw.get("error"):
            entry["error"] = raw["error"]
        return entry

    ratio_id, emp_id, pop_id = source
    emp = by_fred_id.get(emp_id, {"observations": [], "error": "Missing series"})
    pop = by_fred_id.get(pop_id, {"observations": [], "error": "Missing series"})
    entry = {
        "id": ratio_id,
        "age_group": age_group,
        "observations": _emp_pop_ratio_from_levels(
            emp.get("observations") or [],
            pop.get("observations") or [],
        ),
    }
    errors = [e for e in (emp.get("error"), pop.get("error")) if e]
    if errors:
        entry["error"] = "; ".join(errors)
    return entry


def build_labor_age_metrics(
    api_key: str,
    *,
    observation_start: str,
    observation_end: str,
) -> tuple[dict[str, Any], bool]:
    """Fetch unemployment, participation, and emp-pop ratio by age group (BLS via FRED)."""
    flat, all_network_failed = _build_fred_series_bundle(
        api_key,
        observation_start=observation_start,
        observation_end=observation_end,
        series_defs=_flat_series_defs(),
    )
    by_fred_id = {entry["id"]: entry for entry in flat.get("series") or []}

    metrics: list[dict[str, Any]] = []
    for metric_id in (
        LaborAgeMetricId.UNEMPLOYMENT_RATE.value,
        LaborAgeMetricId.LABOR_FORCE_PARTICIPATION.value,
    ):
        metric_name, by_age = _LABOR_AGE_METRIC_DEFINITIONS[metric_id]
        age_series: list[dict[str, Any]] = []
        for age_group in _AGE_GROUPS:
            fred_id = by_age[age_group]
            raw = by_fred_id.get(fred_id, {"id": fred_id, "observations": [], "error": "Missing series"})
            entry: dict[str, Any] = {
                "id": fred_id,
                "age_group": age_group,
                "observations": raw.get("observations") or [],
            }
            if raw.get("error"):
                entry["error"] = raw["error"]
            age_series.append(entry)
        metrics.append({"id": metric_id, "name": metric_name, "series": age_series})

    emp_pop_series = [_emp_pop_series_entry(age_group, by_fred_id) for age_group in _AGE_GROUPS]
    metrics.append(
        {
            "id": LaborAgeMetricId.EMPLOYMENT_POPULATION_RATIO.value,
            "name": "Employment-Population Ratio",
            "series": emp_pop_series,
        }
    )

    payload = {
        "start_date": flat["start_date"],
        "end_date": flat["end_date"],
        "metrics": metrics,
    }
    return payload, all_network_failed
