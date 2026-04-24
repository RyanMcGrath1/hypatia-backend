import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

# Load `.env` next to this file so the key is found even if the process cwd differs
# (e.g. IDE run configs, Flask reloader). Restart the server after editing `.env`.
load_dotenv(Path(__file__).resolve().parent / ".env")

app = Flask(__name__)


def _expo_web_cors_origins() -> list:
    """Origins for Expo web dev server (localhost, loopback, typical LAN, optional extras)."""
    origins: list = [
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        r"^http://\[::1\]:8081$",
        r"^http://192\.168\.\d{1,3}\.\d{1,3}:8081$",
        r"^http://10\.\d{1,3}\.\d{1,3}\.\d{1,3}:8081$",
    ]
    extra = os.environ.get("EXPO_CORS_EXTRA_ORIGINS", "")
    for o in extra.split(","):
        o = o.strip()
        if o:
            origins.append(o)
    return origins


CORS(
    app,
    origins=_expo_web_cors_origins(),
    methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
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
    resp = requests.get(
        url,
        params={"address": address, "key": api_key},
        timeout=30,
    )
    try:
        data = resp.json()
    except ValueError:
        return jsonify({"error": "Invalid response from Google Civic API"}), 502
    return jsonify(data), resp.status_code


def _wants_debug() -> bool:
    """True if FLASK_DEBUG or DEBUG is set to a truthy value (1, true, yes). Default off."""
    for name in ("FLASK_DEBUG", "DEBUG"):
        if os.environ.get(name, "").strip().lower() in ("1", "true", "yes"):
            return True
    return False


if __name__ == "__main__":
    # Bind all interfaces so real devices on Wi‑Fi can reach this API (LAN IP).
    # Equivalent CLI: flask run --host=0.0.0.0 --port=5000
    # Set FLASK_DEBUG=1 (or DEBUG=1) for the interactive debugger and reloader.
    app.run(
        debug=_wants_debug(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
    )
