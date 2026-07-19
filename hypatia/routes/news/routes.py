"""GNews HTTP routes."""

from __future__ import annotations

import os

from flask import jsonify, request

from hypatia.utils.http import missing_env_key_response
from hypatia.routes.news import bp
from hypatia.services.news import SEARCH_PARAMS, build_top_headlines_envelope, fetch_gnews, filter_query_args
from hypatia.utils.settings import Config


@bp.get("/api/news/top-headlines")
def news_top_headlines():
    """Top headlines with page/size pagination (see README)."""
    api_key = os.environ.get(Config.ENV_GNEWS, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_GNEWS)

    data, status = build_top_headlines_envelope(request.args, api_key)
    return jsonify(data), status


@bp.get("/api/news/search")
def news_search():
    """Article search; requires ``q``."""
    api_key = os.environ.get(Config.ENV_GNEWS, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_GNEWS)

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    query = filter_query_args(request.args, SEARCH_PARAMS)
    query["q"] = q
    data, status = fetch_gnews("search", query, api_key)
    return jsonify(data), status
