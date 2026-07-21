"""Premium economy detail screens — Expo ``economyDetailApi.fetchEconomyDetail``."""

from __future__ import annotations

from flask import jsonify, request

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response, observation_end_from_request
from hypatia.services.economy import build_economy_detail, resolve_economy_detail_topic
from hypatia.services.economy.detail import (
    build_gdp_growth_headwinds,
    build_gdp_growth_rate,
    build_gdp_sector_contribution,
    resolve_gdp_growth_observation_window,
)


@bp.get("/api/economy/detail")
def economy_detail():
    """Topic-scoped charts + headline for GDP, labor, inflation, and markets detail views."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    topic = (request.args.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Query parameter 'topic' is required"}), 400

    if resolve_economy_detail_topic(topic) is None:
        return (
            jsonify(
                {
                    "error": "Unknown economy detail topic",
                    "hint": "Use one of: gdp, labor, inflation, markets",
                }
            ),
            404,
        )

    observation_end, bad = observation_end_from_request()
    if bad:
        return bad

    payload = build_economy_detail(
        api_key,
        topic,
        observation_end=observation_end,
    )
    return jsonify(payload), 200


@bp.get("/api/economy/gdp/growth-rate")
def economy_gdp_growth_rate():
    """Real GDP QoQ growth (``A191RL1Q225SBEA``) for the GDP detail growth widget."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    try:
        obs_start, obs_end = resolve_gdp_growth_observation_window(
            request.args.get("observation_start"),
            request.args.get("observation_end"),
        )
    except ValueError as exc:
        return (
            jsonify(
                {
                    "error": str(exc),
                    "hint": (
                        "Use observation_start / observation_end as YYYY-MM-DD "
                        "(default: last ~3 years)."
                    ),
                }
            ),
            400,
        )

    payload, network_failed = build_gdp_growth_rate(
        api_key,
        observation_start=obs_start,
        observation_end=obs_end,
    )
    if network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200


@bp.get("/api/economy/gdp/sector-contribution")
def economy_gdp_sector_contribution():
    """Real value-added share of GDP by industry for the GDP detail sector widget."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_gdp_sector_contribution(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200


@bp.get("/api/economy/gdp/growth-headwinds")
def economy_gdp_growth_headwinds():
    """Macro headwinds for the GDP detail risks panel (freight shipments, fed funds, yield curve, core PCE)."""
    api_key, err = fred_api_key_or_response()
    if err:
        return err

    payload, all_network_failed = build_gdp_growth_headwinds(api_key)
    if all_network_failed:
        return jsonify({"error": "FRED API unavailable"}), 503
    return jsonify(payload), 200
