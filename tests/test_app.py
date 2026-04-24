"""Smoke tests for HTTP routes."""

from app import app


def test_health_returns_ok_json() -> None:
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"message": "hello"}
