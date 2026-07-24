"""Change-email HTTP handlers (request + dual-token verify)."""

from __future__ import annotations

from flask import g, jsonify, request

from hypatia.routes.account import bp
from hypatia.services.account import request_email_change, verify_email_change
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


@bp.post("/api/account/change-email")
@auth_required
def change_email():
    """Start dual-confirmation email change for the authenticated user."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "new_email", "current_password")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    # Do not trim current_password; new_email is normalized in the service.
    result = request_email_change(
        g.current_user,
        new_email=data["new_email"],
        current_password=data["current_password"],
        ip_address=request.remote_addr,
    )
    if not result.ok:
        if result.delivery_failed:
            return jsonify({"error": result.error}), 503
        if result.conflict:
            return jsonify({"error": result.error}), 409
        return jsonify({"error": result.error}), 400

    return jsonify(
        {
            "message": (
                "Confirmation emails sent. Confirm both your current and new "
                "email addresses to complete the change."
            ),
        }
    ), 200


@bp.post("/api/account/change-email/verify")
def verify_change_email():
    """Confirm one side of a pending email change via opaque emailed token."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "token")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    result = verify_email_change(
        raw_token=data["token"],
        ip_address=request.remote_addr,
    )
    if not result.ok:
        if result.conflict:
            return jsonify({"error": result.error}), 409
        return jsonify({"error": result.error}), 400

    return jsonify(
        {
            "message": result.message,
            "email_change_complete": result.email_change_complete,
        }
    ), 200
