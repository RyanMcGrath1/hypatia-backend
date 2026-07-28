"""Profile HTTP routes."""

from flask import Blueprint

bp = Blueprint("profile", __name__)

from hypatia.routes.profile import profile  # noqa: E402, F401
