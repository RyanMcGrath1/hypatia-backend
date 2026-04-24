import os

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

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


@app.get("/api/civic/representatives")
def civic_representatives():
    """Looks up elected representatives for an address via Google Civic Information API."""
    api_key = os.environ.get("GOOGLE_CIVIC_API_KEY", "").strip()
    if not api_key:
        return jsonify(
            {
                "error": "Missing GOOGLE_CIVIC_API_KEY",
                "hint": "Set it in the environment or in a .env file (see .env.example).",
            }
        ), 503

    address = request.args.get("address", "").strip()
    if not address:
        return jsonify({"error": "Query parameter 'address' is required"}), 400

    url = f"{GOOGLE_CIVIC_BASE}/representatives"
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


if __name__ == "__main__":
    # Bind all interfaces so real devices on Wi‑Fi can reach this API (LAN IP).
    # Equivalent CLI: flask run --host=0.0.0.0 --port=5000
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
