"""GNews HTTP routes."""

from __future__ import annotations

import os

from flask import jsonify, request

from hypatia.utils.http import missing_env_key_response
from hypatia.routes.news import bp
from hypatia.services.news import build_top_headlines_envelope
from hypatia.utils.settings import Config


@bp.get("/api/news/top-headlines")
def news_top_headlines():
    """Top headlines with page/size pagination (see README)."""
    api_key = os.environ.get(Config.ENV_GNEWS, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_GNEWS)

    data, status = build_top_headlines_envelope(request.args, api_key)
    return jsonify(data), status
