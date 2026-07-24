"""Logout HTTP handler."""

from __future__ import annotations

from flask import g, jsonify

from hypatia.routes.auth import bp
from hypatia.services.auth.sessions import revoke_session
from hypatia.utils.auth import auth_required


@bp.post("/api/auth/logout")
@auth_required
def logout():
    """Revoke the current session server-side."""
    revoke_session(g.current_session)
    return jsonify({"message": "Logout successful"}), 200
