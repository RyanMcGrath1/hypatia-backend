"""Smoke tests for HTTP routes."""


def test_health_returns_ok_json(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"message": "hello"}


def test_unknown_path_returns_json_not_found(client) -> None:
    response = client.get("/no/such/route")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Not Found"}
