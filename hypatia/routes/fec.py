"""OpenFEC API proxy routes."""

from __future__ import annotations

import os
import time

import requests
from flask import Blueprint, jsonify, request

from hypatia.http import missing_env_key_response, truthy_query_flag
from hypatia.logging_config import log_upstream
from hypatia.settings import Config

bp = Blueprint("fec", __name__)


@bp.get("/api/fec/v1/names/candidates")
@bp.get("/api/fec/candidates")
def fec_names_candidates():
    """Proxy for OpenFEC ``GET /v1/names/candidates/`` (key from env only).

    Query: ``q`` or ``name`` (alias → ``q``). Optional ``page``, ``per_page``
    (defaults to 5). ``typeahead=1`` uses a shorter timeout for live search UIs.
    """
    api_key = os.environ.get(Config.ENV_OPENFEC, "").strip()
    if not api_key:
        return missing_env_key_response(Config.ENV_OPENFEC)

    q = request.args.get("q", "").strip() or request.args.get("name", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required (alias: 'name')"}), 400

    typeahead = truthy_query_flag(request.args.get("typeahead"))

    params: dict[str, str] = {"api_key": api_key, "q": q}
    per_page_from_client = False
    for key in ("page", "per_page"):
        raw = request.args.get(key, "").strip()
        if raw:
            params[key] = raw
            if key == "per_page":
                per_page_from_client = True
    if not per_page_from_client:
        params["per_page"] = str(Config.OPENFEC_NAMES_PER_PAGE_DEFAULT)

    url = f"{Config.OPENFEC_BASE}/names/candidates/"
    timeout = Config.OPENFEC_TYPEAHEAD_TIMEOUT_S if typeahead else Config.OPENFEC_DEFAULT_TIMEOUT_S
    t0 = time.perf_counter()
    resp = requests.get(url, params=params, timeout=timeout)
    log_upstream(
        "hypatia.upstream",
        service="open_fec",
        endpoint="names/candidates",
        status_code=resp.status_code,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    try:
        data = resp.json()
    except ValueError:
        return jsonify({"error": "Invalid response from OpenFEC API"}), 502
    return jsonify(data), resp.status_code
