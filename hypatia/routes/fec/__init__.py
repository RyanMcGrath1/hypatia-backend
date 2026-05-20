"""FEC API — Expo ``fecCandidatesApi``."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("fec", __name__)

from hypatia.routes.fec import routes  # noqa: E402, F401
