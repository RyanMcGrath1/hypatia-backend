"""Economy API — mirrors Expo ``hooks/api/`` economy clients (dashboard, labor, rates, GDP, etc.)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("economy", __name__)

from hypatia.routes.economy import (  # noqa: E402, F401
    cpi,
    detail,
    economy_controller,
    inflation_cpi_components,
    inflation_pce_vs_target,
    labor_market_controller,
    rates_fed_funds_target,
    rates_key_metrics,
)

# Controllers with their own ``url_prefix``; nest under this package blueprint.
bp.register_blueprint(economy_controller.bp)
bp.register_blueprint(labor_market_controller.bp)
