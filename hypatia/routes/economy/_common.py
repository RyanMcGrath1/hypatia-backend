"""Shared helpers for economy HTTP handlers."""

from __future__ import annotations

import os
import re

from flask import jsonify, request

from hypatia.http import missing_env_key_response
from hypatia.services.economy import resolve_sector_dashboard_observation_window
from hypatia.settings import Config

_OVERVIEW_OBSERVATION_END_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fred_api_key_or_response():
    """Return FRED API key string, or a Flask (response, status) tuple when missing."""
    api_key = os.environ.get(Config.ENV_FRED, "").strip()
    if not api_key:
        return None, missing_env_key_response(Config.ENV_FRED)
    return api_key, None


def observation_end_from_request() -> tuple[str | None, tuple | None]:
    """Parse optional ``observation_end``; return (value, error_response) if invalid."""
    observation_end = (request.args.get("observation_end") or "").strip()
    if observation_end and _OVERVIEW_OBSERVATION_END_RE.fullmatch(observation_end) is None:
        return None, (
            jsonify(
                {
                    "error": "Invalid observation_end",
                    "hint": "Use YYYY-MM-DD (e.g. 2025-11-01)",
                }
            ),
            400,
        )
    return observation_end or None, None


def sector_window_from_request() -> tuple[tuple[str, str] | None, tuple | None]:
    """Resolve YTD/default sector window from query; return ((start, end), error_response)."""
    try:
        return (
            resolve_sector_dashboard_observation_window(
                request.args.get("observation_start"),
                request.args.get("observation_end"),
            ),
            None,
        )
    except ValueError as exc:
        return None, (
            jsonify(
                {
                    "error": str(exc),
                    "hint": (
                        "Use observation_start / observation_end as YYYY-MM-DD (default: YTD UTC)."
                    ),
                }
            ),
            400,
        )
