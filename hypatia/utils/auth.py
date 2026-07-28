"""Bearer-token authentication helpers for protected routes."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Response, g, jsonify, request

from hypatia.extensions import db
from hypatia.services.auth.constants import UNAUTHENTICATED_MESSAGE
from hypatia.services.auth.sessions import validate_session

F = TypeVar("F", bound=Callable[..., Any])


def extract_bearer_token() -> str | None:
    """Parse ``Authorization: Bearer <token>``; return None when missing or malformed."""
    header = request.headers.get("Authorization")
    if header is None:
        return None

    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1].strip()
    if token == "":
        return None

    return token


def authenticate_request() -> Response | None:
    """Validate Bearer session token and populate ``g.current_user`` / ``g.current_session``."""
    raw_token = extract_bearer_token()
    if raw_token is None:
        return jsonify({"error": UNAUTHENTICATED_MESSAGE}), 401

    result = validate_session(raw_token)
    if not result.valid or result.user is None or result.session is None:
        return jsonify({"error": UNAUTHENTICATED_MESSAGE}), 401

    g.current_user = result.user
    g.current_session = result.session
    return None


def auth_required(view: F) -> F:
    """Decorator that requires a valid opaque session Bearer token."""

    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        error_response = authenticate_request()
        if error_response is not None:
            return error_response
        try:
            return view(*args, **kwargs)
        finally:
            db.session.commit()

    return wrapped  # type: ignore[return-value]
