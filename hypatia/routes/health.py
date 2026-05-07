"""Root and health-check routes."""

from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/")
def index() -> str:
    return "Hello, Flask!"


@bp.get("/hello")
def hello_health():
    """JSON smoke check."""
    return jsonify({"message": "hello"}), 200


@bp.get("/health")
def health():
    """Same payload as ``/hello``; friendly for load balancers."""
    return hello_health()
