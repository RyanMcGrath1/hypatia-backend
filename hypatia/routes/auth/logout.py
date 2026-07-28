"""Logout HTTP handler."""

from __future__ import annotations

from flask import g, jsonify

from hypatia.routes.auth import bp
from hypatia.services.audit import get_audit_request_context
from hypatia.services.auth.sessions import logout_session
from hypatia.utils.auth import auth_required


@bp.post("/api/auth/logout")
@auth_required
def logout():
    """Revoke the current session and record a LOGOUT account event."""
    audit = get_audit_request_context()
    logout_session(
        g.current_user,
        g.current_session,
        **audit.as_kwargs(),
    )
    return jsonify({"message": "Logout successful"}), 200
