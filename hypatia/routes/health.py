"""Health-check route."""

from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """JSON liveness check for load balancers."""
    return jsonify({"message": "hello"}), 200
