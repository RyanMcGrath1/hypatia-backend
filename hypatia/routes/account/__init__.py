"""Account HTTP routes."""

from flask import Blueprint

bp = Blueprint("account", __name__)

from hypatia.routes.account import password  # noqa: E402, F401
