"""Login HTTP handler."""

from __future__ import annotations

from flask import jsonify, request

from hypatia.extensions import db
from hypatia.routes.auth import bp
from hypatia.services.auth.authentication import authenticate_user
from hypatia.services.auth.constants import INVALID_CREDENTIALS_MESSAGE
from hypatia.services.auth.mfa_challenge import complete_totp_login, create_mfa_login_challenge
from hypatia.services.auth.sessions import create_session


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


@bp.post("/api/auth/login")
def login():
    """Validate credentials; return a Session or an MFA challenge when required."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "email", "password")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    email: str = data["email"]
    password: str = data["password"]

    result = authenticate_user(
        email,
        password,
        ip_address=request.remote_addr,
        commit=False,
    )
    if not result.success or result.user is None:
        return jsonify({"error": INVALID_CREDENTIALS_MESSAGE}), 401

    if result.mfa_required:
        challenge_token = create_mfa_login_challenge(result.user)
        db.session.commit()
        return jsonify(
            {
                "mfa_required": True,
                "mfa_method": "totp",
                "challenge_token": challenge_token,
            }
        ), 200

    raw_token, _session = create_session(result.user)
    db.session.commit()

    return jsonify({"message": "Login successful", "token": raw_token}), 200


@bp.post("/api/auth/login/totp")
def login_totp():
    """Complete MFA login with a challenge token and authenticator code."""
    data = request.get_json(silent=True)
    field_errors = _json_field_errors(data, "challenge_token", "code")
    if field_errors:
        return jsonify({"error": field_errors[0]}), 400

    assert isinstance(data, dict)
    result = complete_totp_login(
        challenge_token=data["challenge_token"],
        code=data["code"],
        ip_address=request.remote_addr,
    )
    if not result.ok or result.raw_token is None:
        return jsonify({"error": result.error or INVALID_CREDENTIALS_MESSAGE}), 401

    return jsonify({"message": "Login successful", "token": result.raw_token}), 200
