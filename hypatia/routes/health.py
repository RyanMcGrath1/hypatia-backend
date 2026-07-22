"""Health-check route."""

from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


def _health_payload():
    return jsonify({"message": "hello"}), 200


@bp.get("/health")
def health():
    """JSON liveness check for load balancers."""
    return _health_payload()
