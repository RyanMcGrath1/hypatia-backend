"""Security HTTP routes (TOTP MFA)."""

from flask import Blueprint

bp = Blueprint("security", __name__)

from hypatia.routes.security import totp  # noqa: E402, F401
