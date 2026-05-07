"""Shared HTTP / JSON response helpers."""

from __future__ import annotations

from flask import jsonify

from hypatia.settings import truthy_from_str


def missing_env_key_response(env_var: str):
    """503 JSON when a required API key env var is unset or empty."""
    return (
        jsonify(
            {
                "error": f"Missing {env_var}",
                "hint": (
                    f"Set {env_var} in `.env` (see .env.example) or the environment, "
                    "then fully restart this server (stop and start; "
                    "required after creating/editing `.env`)."
                ),
            }
        ),
        503,
    )


def truthy_query_flag(value: str | None) -> bool:
    return truthy_from_str(value, default=False)
