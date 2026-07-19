"""FRED-backed economy aggregation."""

from hypatia.services.economy.core import (
    CPI_RECENT_MONTHS,
    CPI_SERIES_ID,
    EMPLOYMENT_SECTOR_SERIES,
    FRED_OBSERVATIONS_URL,
    FRED_REQUEST_TIMEOUT,
    LABOR_EARNINGS_INFLATION_SERIES,
    OVERVIEW_SERIES,
    build_cpi_recent,
    build_economy_overview,
    build_economy_overview_sector,
    build_employment_sectors,
    build_labor_earnings_inflation,
    fetch_fred_series,
    resolve_economy_dashboard_sector,
    resolve_sector_dashboard_observation_window,
)
from hypatia.services.economy.detail import build_economy_detail, resolve_economy_detail_topic
from hypatia.services.economy.labor_age_metrics import build_labor_age_metrics
from hypatia.services.economy.cpi_components import build_cpi_components
from hypatia.services.economy.pce_vs_target import build_pce_vs_target

__all__ = [
    "CPI_RECENT_MONTHS",
    "CPI_SERIES_ID",
    "EMPLOYMENT_SECTOR_SERIES",
    "FRED_OBSERVATIONS_URL",
    "FRED_REQUEST_TIMEOUT",
    "LABOR_EARNINGS_INFLATION_SERIES",
    "OVERVIEW_SERIES",
    "build_cpi_recent",
    "build_economy_detail",
    "build_economy_overview",
    "build_economy_overview_sector",
    "build_employment_sectors",
    "build_labor_earnings_inflation",
    "build_labor_age_metrics",
    "build_cpi_components",
    "build_pce_vs_target",
    "fetch_fred_series",
    "resolve_economy_dashboard_sector",
    "resolve_economy_detail_topic",
    "resolve_sector_dashboard_observation_window",
]
