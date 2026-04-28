"""Tests for GNews proxy routes (mocked HTTP)."""

import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from app import app


@pytest.fixture
def client():
    return app.test_client()


@responses.activate
def test_news_missing_gnews_key(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": ""}):
        r = client.get("/api/news/top-headlines")
    assert r.status_code == 503
    assert r.get_json()["error"] == "Missing GNEWS_API_KEY"


@responses.activate
def test_news_search_missing_q(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": "test_key"}):
        r = client.get("/api/news/search")
    assert r.status_code == 400
    assert r.get_json()["error"] == "Query parameter 'q' is required"


@responses.activate
def test_news_top_headlines_forwards_whitelisted_params(client):
    responses.add(
        responses.GET,
        "https://gnews.io/api/v4/top-headlines",
        json={"articles": [], "totalArticles": 0},
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get(
            "/api/news/top-headlines?category=technology&lang=en&max=5&apikey=should_be_ignored"
        )
    assert r.status_code == 200
    assert r.get_json() == {"articles": [], "totalArticles": 0}
    assert len(responses.calls) == 1
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["apikey"] == ["secret"]
    assert qs["category"] == ["technology"]
    assert qs["lang"] == ["en"]
    assert qs["max"] == ["5"]
    assert "should_be_ignored" not in qs.get("apikey", [])


@responses.activate
def test_news_search_forwards_q(client):
    responses.add(
        responses.GET,
        "https://gnews.io/api/v4/search",
        json={"articles": [{"title": "x"}], "totalArticles": 1},
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/search?q=climate&lang=en")
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["q"] == ["climate"]
    assert qs["lang"] == ["en"]
    assert qs["apikey"] == ["secret"]


@responses.activate
def test_news_invalid_upstream_json(client):
    responses.add(
        responses.GET,
        "https://gnews.io/api/v4/top-headlines",
        body="NOT JSON",
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines")
    assert r.status_code == 502
    assert r.get_json()["error"] == "Invalid response from GNews API"
