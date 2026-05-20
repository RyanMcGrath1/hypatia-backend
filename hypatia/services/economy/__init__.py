"""FRED-backed economy aggregation."""

from hypatia.services.economy.core import (
    EMPLOYMENT_SECTOR_SERIES,
    FRED_OBSERVATIONS_URL,
    FRED_REQUEST_TIMEOUT,
    OVERVIEW_SERIES,
    build_economy_overview,
    build_economy_overview_sector,
    build_employment_sectors,
    fetch_fred_series,
    resolve_economy_dashboard_sector,
    resolve_sector_dashboard_observation_window,
)
from hypatia.services.economy.detail import build_economy_detail, resolve_economy_detail_topic

__all__ = [
    "EMPLOYMENT_SECTOR_SERIES",
    "FRED_OBSERVATIONS_URL",
    "FRED_REQUEST_TIMEOUT",
    "OVERVIEW_SERIES",
    "build_economy_detail",
    "build_economy_overview",
    "build_economy_overview_sector",
    "build_employment_sectors",
    "fetch_fred_series",
    "resolve_economy_dashboard_sector",
    "resolve_economy_detail_topic",
    "resolve_sector_dashboard_observation_window",
]
