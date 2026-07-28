"""Authentication HTTP routes."""

from flask import Blueprint

bp = Blueprint("auth", __name__)

from hypatia.routes.auth import login, logout, register  # noqa: E402, F401
