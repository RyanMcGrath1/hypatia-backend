"""Backward-compatible import path; implementation lives in ``hypatia.services.economy``."""

from hypatia.services.economy.core import *  # noqa: F403
from hypatia.services.economy.core import (  # noqa: F401 — pytest patch targets
    _sector_dashboard_clock_today,
    fetch_fred_series,
)
