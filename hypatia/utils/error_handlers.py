"""JSON error responses for API clients (load balancers, mobile apps)."""

from __future__ import annotations

from flask import Flask, jsonify


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_exc):
        return jsonify({"error": "Not Found"}), 404

    @app.errorhandler(500)
    def internal_error(_exc):
        return jsonify({"error": "Internal Server Error"}), 500
