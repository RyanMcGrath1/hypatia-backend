"""JSON error responses for API clients (load balancers, mobile apps)."""

from __future__ import annotations

import time

from flask import Flask, jsonify

from hypatia.services.auth.rate_limit import AUTH_RATE_LIMITED_MESSAGE


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_exc):
        return jsonify({"error": "Not Found"}), 404

    @app.errorhandler(500)
    def internal_error(_exc):
        return jsonify({"error": "Internal Server Error"}), 500

    @app.errorhandler(429)
    def too_many_requests(_exc):
        """Generic auth rate-limit response (no counters, keys, or auth state)."""
        response = jsonify({"error": AUTH_RATE_LIMITED_MESSAGE})
        response.status_code = 429

        # Preserve a safe Retry-After when Flask-Limiter exposes the active window.
        try:
            from hypatia.extensions import limiter

            current = limiter.current_limit
            if current is not None and getattr(current, "reset_at", None) is not None:
                retry_after = max(int(current.reset_at - time.time()), 0)
                response.headers["Retry-After"] = str(retry_after)
        except Exception:
            pass

        return response
