"""Registration HTTP handler."""

from __future__ import annotations

from flask import jsonify, request

from hypatia.routes.auth import bp
from hypatia.services.auth.registration import register_user


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


@bp.post("/api/auth/register")
def register():
    """Create a User + Profile and return a new opaque session token."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(
        data,
        "email",
        "password",
        "first_name",
        "last_name",
    )
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    result = register_user(
        data["email"],
        data["password"],
        data["first_name"],
        data["last_name"],
        ip_address=request.remote_addr,
    )
    if not result.ok:
        status = 409 if result.conflict else 400
        return jsonify({"error": result.error}), status

    return jsonify(
        {
            "message": "Registration successful",
            "token": result.raw_token,
        }
    ), 201
