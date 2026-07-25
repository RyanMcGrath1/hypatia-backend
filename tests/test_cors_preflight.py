"""CORS preflight regression for Expo Web → Flask auth/API flows."""

from __future__ import annotations

import pytest

DEV_ORIGIN = "http://localhost:8081"


def _allow_headers(response) -> set[str]:
    raw = response.headers.get("Access-Control-Allow-Headers", "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _allow_methods(response) -> set[str]:
    raw = response.headers.get("Access-Control-Allow-Methods", "")
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


@pytest.mark.parametrize(
    ("path", "method", "request_headers", "required_headers"),
    [
        (
            "/api/auth/register",
            "POST",
            "content-type,x-request-id",
            {"content-type", "x-request-id"},
        ),
        (
            "/api/profile",
            "PATCH",
            "authorization,content-type,x-request-id",
            {"authorization", "content-type", "x-request-id"},
        ),
        (
            "/api/security/totp/setup",
            "DELETE",
            "authorization,content-type,x-request-id",
            {"authorization", "content-type", "x-request-id"},
        ),
    ],
)
def test_cors_preflight_allows_expo_dev_origin_headers_and_methods(
    client,
    path: str,
    method: str,
    request_headers: str,
    required_headers: set[str],
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": DEV_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": request_headers,
        },
    )

    assert response.status_code in (200, 204)
    assert response.headers.get("Access-Control-Allow-Origin") == DEV_ORIGIN

    allowed_headers = _allow_headers(response)
    assert required_headers.issubset(allowed_headers)

    allowed_methods = _allow_methods(response)
    assert method in allowed_methods
    assert "OPTIONS" in allowed_methods
