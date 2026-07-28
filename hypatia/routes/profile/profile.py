"""Authenticated Profile HTTP handlers."""

from __future__ import annotations

from flask import g, jsonify, request

from hypatia.routes.profile import bp
from hypatia.services.profile import get_profile, update_profile
from hypatia.utils.auth import auth_required


@bp.get("/api/profile")
@auth_required
def get_current_profile():
    """Return the authenticated user's Profile page fields."""
    result = get_profile(g.current_user)
    if result.missing_profile:
        return jsonify({"error": result.error}), 500
    assert result.profile is not None
    return jsonify(result.profile.as_dict()), 200


@bp.patch("/api/profile")
@auth_required
def patch_current_profile():
    """Update the authenticated user's first_name and/or last_name."""
    data = request.get_json(silent=True)
    result = update_profile(g.current_user, data)
    if result.missing_profile:
        return jsonify({"error": result.error}), 500
    if not result.ok or result.profile is None:
        return jsonify({"error": result.error}), 400
    return jsonify(result.profile.as_dict()), 200
