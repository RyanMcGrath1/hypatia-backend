"""Account HTTP routes."""

from flask import Blueprint

bp = Blueprint("account", __name__)

from hypatia.routes.account import delete, email_change, password  # noqa: E402, F401
