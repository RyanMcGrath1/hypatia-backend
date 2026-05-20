"""Premium economy detail screens — Expo ``economyDetailApi.fetchEconomyDetail``."""

from __future__ import annotations

from flask import jsonify, request

from hypatia.routes.economy import bp
from hypatia.routes.economy._common import fred_api_key_or_response, observation_end_from_request
from hypatia.services.economy import build_economy_detail, resolve_economy_detail_topic


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
