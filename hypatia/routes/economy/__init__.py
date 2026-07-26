"""Economy API — mirrors Expo ``hooks/api/`` economy clients (dashboard, labor, rates, GDP, etc.)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("economy", __name__)

from hypatia.routes.economy import (  # noqa: E402, F401
    detail,
    economy_controller,
    inflation_controller,
    interest_rates_controller,
    labor_market_controller,
)

# Controllers with their own ``url_prefix``; nest under this package blueprint.
bp.register_blueprint(economy_controller.bp)
bp.register_blueprint(labor_market_controller.bp)
bp.register_blueprint(inflation_controller.bp)
bp.register_blueprint(interest_rates_controller.bp)
