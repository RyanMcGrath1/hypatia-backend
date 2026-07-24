"""Change-password HTTP handler."""

from __future__ import annotations

from flask import g, jsonify, request

from hypatia.routes.account import bp
from hypatia.services.account import change_user_password
from hypatia.utils.auth import auth_required


def _json_field_errors(data: object, *fields: str) -> list[str]:
    if not isinstance(data, dict):
        return [f"{field} is required" for field in fields]

    errors: list[str] = []
    for field in fields:
        if field not in data:
            errors.append(f"{field} is required")
        elif not isinstance(data[field], str):
            errors.append(f"{field} must be a string")
    return errors


@bp.post("/api/account/change-password")
@auth_required
def change_password():
    """Change the authenticated user's password and rotate their session."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(
        data,
        "current_password",
        "new_password",
        "confirm_new_password",
    )
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    # Do not trim or normalize any password field.
    result = change_user_password(
        g.current_user,
        g.current_session,
        current_password=data["current_password"],
        new_password=data["new_password"],
        confirm_new_password=data["confirm_new_password"],
        ip_address=request.remote_addr,
    )
    if not result.ok:
        # 400: request is already authenticated; this is a field/credential
        # check on a protected action (not a missing/invalid Bearer session).
        return jsonify({"error": result.error}), 400

    return jsonify(
        {
            "message": "Password changed successfully",
            "token": result.raw_token,
            "password_changed_at": result.password_changed_at,
        }
    ), 200
