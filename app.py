import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from economy import build_economy_overview, build_economy_summary
from news import (
    SEARCH_PARAMS,
    build_top_headlines_envelope,
    fetch_gnews,
    filter_query_args,
)
from request_logging import configure_logging, log_upstream, register_request_logging

# Load `.env` next to this file so the key is found even if the process cwd differs
# (e.g. IDE run configs, Flask reloader). Restart the server after editing `.env`.
load_dotenv(Path(__file__).resolve().parent / ".env")

app = Flask(__name__)
configure_logging(app)
register_request_logging(app)


def _expo_cors_origins():
    """Origins allowed for local Expo / React Native dev (machine + phone on LAN).

    Covers Metro/Expo dev server on common ports, any port on localhost, and private
    LAN ranges so a physical device can load JS from http://<your-pc-ip>:8081 (etc.)
    while calling this API. Set CORS_ALLOW_ALL_ORIGINS=1 for maximum permissiveness
    during local dev only (do not use in production).
    """
    if os.environ.get("CORS_ALLOW_ALL_ORIGINS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return "*"

    origins: list = [
        # Expo / Metro often use 8081; also 19000, 19006, 8082, etc.
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:19000",
        "http://127.0.0.1:19000",
        "http://localhost:19006",
        "http://127.0.0.1:19006",
        # Any port on loopback (simulator, Expo web, alternate Metro ports)
        r"^http://localhost:\d+$",
        r"^http://127\.0\.0\.1:\d+$",
        r"^http://\[::1\]:\d+$",
        # Phone on Wi‑Fi: bundle from http://<lan-ip>:<metro-port>
        r"^http://192\.168\.\d{1,3}\.\d{1,3}:\d+$",
        r"^http://10\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$",
        r"^http://172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}:\d+$",
        # Some WebView / RN stacks send Origin: null
        "null",
    ]
    extra = os.environ.get("EXPO_CORS_EXTRA_ORIGINS", "")
    for o in extra.split(","):
        o = o.strip()
        if o:
            origins.append(o)
    return origins


CORS(
    app,
    origins=_expo_cors_origins(),
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
    expose_headers=["X-Request-ID"],
)

GOOGLE_CIVIC_BASE = "https://www.googleapis.com/civicinfo/v2"


@app.get("/")
def index() -> str:
    return "Hello, Flask!"


@app.get("/hello")
def hello_health():
    """Smoke / health for Hypatia: 200 + JSON the client can parse."""
    return jsonify({"message": "hello"}), 200


@app.get("/health")
def health():
    """Load-balancer friendly health check; same payload as /hello."""
    return hello_health()


def _missing_civic_key_response():
    return (
        jsonify(
            {
                "error": "Missing GOOGLE_CIVIC_API_KEY",
                "hint": (
                    "Set GOOGLE_CIVIC_API_KEY in `.env` (see .env.example) or the environment, "
                    "then fully restart this server (stop and start; required after creating/editing `.env`)."
                ),
            }
        ),
        503,
    )


def _missing_fred_key_response():
    return (
        jsonify(
            {
                "error": "Missing FRED_API_KEY",
                "hint": (
                    "Set FRED_API_KEY in `.env` (see .env.example) or the environment, "
                    "then fully restart this server (stop and start; required after creating/editing `.env`)."
                ),
            }
        ),
        503,
    )


def _missing_gnews_key_response():
    return (
        jsonify(
            {
                "error": "Missing GNEWS_API_KEY",
                "hint": (
                    "Set GNEWS_API_KEY in `.env` (see .env.example) or the environment, "
                    "then fully restart this server (stop and start; required after creating/editing `.env`)."
                ),
            }
        ),
        503,
    )


@app.get("/api/civic/representatives")
def civic_representatives_gone():
    """Google turned down the Representatives API in 2025; use divisions-by-address instead."""
    return jsonify(
        {
            "error": "The Google Civic Representatives API is no longer available.",
            "use_instead": "/api/civic/divisions-by-address",
            "hint": "Use GET /api/civic/divisions-by-address?address=... for OCD division IDs (see Google Civic docs).",
        }
    ), 410


@app.get("/api/civic/divisions-by-address")
def civic_divisions_by_address():
    """Looks up political geographic divisions (OCD IDs) for an address via Google Civic Information API."""
    api_key = os.environ.get("GOOGLE_CIVIC_API_KEY", "").strip()
    if not api_key:
        return _missing_civic_key_response()

    address = request.args.get("address", "").strip()
    if not address:
        return jsonify({"error": "Query parameter 'address' is required"}), 400

    url = f"{GOOGLE_CIVIC_BASE}/divisionsByAddress"
    t0 = time.perf_counter()
    resp = requests.get(
        url,
        params={"address": address, "key": api_key},
        timeout=30,
    )
    log_upstream(
        "hypatia.upstream",
        service="google_civic",
        endpoint="divisionsByAddress",
        status_code=resp.status_code,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    try:
        data = resp.json()
    except ValueError:
        return jsonify({"error": "Invalid response from Google Civic API"}), 502
    return jsonify(data), resp.status_code


# --- Economy (FRED) ---
# Single snapshot GET /api/economy/summary: all v1 tiles use the same FRED
# `series/observations` upstream, so one client round-trip, one shared `as_of`,
# parallel upstream fetches (see economy.py), and saner rate-limit behavior than
# N separate client→server→FRED chains. Partial upstream failures return HTTP 200
# with per-tile `error` / `hint` so the client can still render other tiles.


@app.get("/api/economy/summary")
def economy_summary():
    """Latest (and optional prior) FRED observations for configured economy tiles."""
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        return _missing_fred_key_response()

    payload = build_economy_summary(api_key)
    return jsonify(payload), 200


@app.get("/api/economy/overview")
def economy_overview():
    """FRED: two most recent observations per overview series (see economy.py)."""
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        return _missing_fred_key_response()

    payload = build_economy_overview(api_key)
    return jsonify(payload), 200


# --- GNews (https://gnews.io/api/v4) ---
# Proxies top headlines and search; API key stays server-side only.


@app.get("/api/news/top-headlines")
def news_top_headlines():
    """GNews top headlines with page/max pagination (see README)."""
    api_key = os.environ.get("GNEWS_API_KEY", "").strip()
    if not api_key:
        return _missing_gnews_key_response()

    data, status = build_top_headlines_envelope(request.args, api_key)
    return jsonify(data), status


@app.get("/api/news/search")
def news_search():
    """Keyword search over articles; requires query parameter q."""
    api_key = os.environ.get("GNEWS_API_KEY", "").strip()
    if not api_key:
        return _missing_gnews_key_response()

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    query = filter_query_args(request.args, SEARCH_PARAMS)
    query["q"] = q
    data, status = fetch_gnews("search", query, api_key)
    return jsonify(data), status


def _wants_debug() -> bool:
    """True if FLASK_DEBUG or DEBUG is set to a truthy value (1, true, yes). Default off."""
    for name in ("FLASK_DEBUG", "DEBUG"):
        if os.environ.get(name, "").strip().lower() in ("1", "true", "yes"):
            return True
    return False


if __name__ == "__main__":
    # Bind all interfaces so real devices on Wi‑Fi can reach this API (LAN IP).
    # Equivalent CLI: flask run --host=0.0.0.0 --port=5001
    # Set FLASK_DEBUG=1 (or DEBUG=1) for the interactive debugger and reloader.
    app.run(
        debug=_wants_debug(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5001")),
    )
