"""TOTP authenticator-app HTTP handlers."""

from __future__ import annotations

from flask import g, jsonify, request

from hypatia.routes.security import bp
from hypatia.services.audit import get_audit_request_context
from hypatia.services.security import disable_totp, enable_totp, setup_totp
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


@bp.post("/api/security/totp/setup")
@auth_required
def totp_setup():
    """Begin TOTP enrollment after current-password reauthentication."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "current_password")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    result = setup_totp(g.current_user, current_password=data["current_password"])
    if not result.ok:
        return jsonify({"error": result.error}), 400

    return jsonify(
        {
            "provisioning_uri": result.provisioning_uri,
            "manual_entry_key": result.manual_entry_key,
        }
    ), 200


@bp.post("/api/security/totp/enable")
@auth_required
def totp_enable():
    """Confirm pending TOTP setup and rotate sessions."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "code")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    audit = get_audit_request_context()
    result = enable_totp(
        g.current_user,
        g.current_session,
        code=data["code"],
        **audit.as_kwargs(),
    )
    if not result.ok:
        return jsonify({"error": result.error}), 400

    return jsonify(
        {
            "message": "Authenticator app enabled",
            "token": result.raw_token,
            "totp_enabled": True,
        }
    ), 200


@bp.post("/api/security/totp/disable")
@auth_required
def totp_disable():
    """Disable TOTP after password + authenticator-code reauthentication."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "current_password", "code")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    audit = get_audit_request_context()
    result = disable_totp(
        g.current_user,
        g.current_session,
        current_password=data["current_password"],
        code=data["code"],
        **audit.as_kwargs(),
    )
    if not result.ok:
        return jsonify({"error": result.error}), 400

    return jsonify(
        {
            "message": "Authenticator app disabled",
            "token": result.raw_token,
            "totp_enabled": False,
        }
    ), 200
