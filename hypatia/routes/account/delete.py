"""Delete-account HTTP handler."""

from __future__ import annotations

from flask import g, jsonify, request

from hypatia.routes.account import bp
from hypatia.services.account import (
    ACCOUNT_DELETED_MESSAGE,
    CONFIRMATION_REQUIRED_MESSAGE,
    delete_account,
)
from hypatia.utils.auth import auth_required


def _required_string_errors(data: object, *fields: str) -> list[str]:
    if not isinstance(data, dict):
        return [f"{field} is required" for field in fields]

    errors: list[str] = []
    for field in fields:
        if field not in data:
            errors.append(f"{field} is required")
        elif not isinstance(data[field], str):
            errors.append(f"{field} must be a string")
    return errors


@bp.delete("/api/account")
@auth_required
def delete_account_route():
    """Soft-delete the authenticated user's account after reauthentication."""
    data = request.get_json(silent=True)
    field_errors = _required_string_errors(data, "current_password", "confirmation")
    if field_errors:
        # Prefer the confirmation-specific message when that field is missing.
        if (
            isinstance(data, dict)
            and "confirmation" not in data
            and "current_password" in data
        ):
            return jsonify({"error": CONFIRMATION_REQUIRED_MESSAGE}), 400
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)

    totp_code_provided = "totp_code" in data
    totp_code = data.get("totp_code")
    if totp_code_provided and not isinstance(totp_code, str):
        return jsonify({"error": "totp_code must be a string"}), 400

    # Do not trim confirmation or password fields.
    result = delete_account(
        g.current_user,
        g.current_session,
        current_password=data["current_password"],
        confirmation=data["confirmation"],
        totp_code=totp_code if totp_code_provided else None,
        totp_code_provided=totp_code_provided,
        ip_address=request.remote_addr,
    )
    if not result.ok:
        return jsonify({"error": result.error}), 400

    return jsonify({"message": ACCOUNT_DELETED_MESSAGE}), 200
