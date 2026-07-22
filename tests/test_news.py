"""Tests for GNews proxy routes (mocked HTTP)."""

import json
import os
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import responses

@responses.activate
def test_news_missing_gnews_key(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": ""}):
        r = client.get("/api/news/top-headlines")
    assert r.status_code == 503
    assert r.get_json()["error"] == "Missing GNEWS_API_KEY"

@responses.activate
def test_news_top_headlines_first_page_defaults(client):
    responses.add(
        responses.GET,
        re.compile(r"https://gnews\.io/api/v4/top-headlines\?"),
        json={"articles": [], "totalArticles": 0},
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines")
    assert r.status_code == 200
    body = r.get_json()
    assert body["items"] == []
    assert body["articles"] == []
    assert body["hasMore"] is False
    assert body["nextPage"] is None
    assert body["nextOffset"] is None
    assert body["nextCursor"] is None
    assert body["page"] == 1
    assert body["max"] == 20
    assert body["total"] == 0
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["apikey"] == ["secret"]
    assert qs["page"] == ["1"]
    assert qs["max"] == ["20"]

@responses.activate
def test_news_top_headlines_forwards_filters_clamps_max_ignores_cache_buster(client):
    responses.add(
        responses.GET,
        re.compile(r"https://gnews\.io/api/v4/top-headlines\?"),
        json={
            "articles": [
                {"title": "x", "publishedAt": "2024-01-02T00:00:00Z"},
            ],
            "totalArticles": 1,
        },
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get(
            "/api/news/top-headlines?category=technology&lang=en&max=100&apikey=ignored&_=1730000000"
        )
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["category"] == ["technology"]
    assert qs["lang"] == ["en"]
    assert qs["max"] == ["50"]
    assert qs["page"] == ["1"]
    assert "_" not in qs
    assert qs["apikey"] == ["secret"]

@responses.activate
def test_news_top_headlines_second_page_has_more(client):
    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        page = (qs.get("page") or ["1"])[0]
        if page == "1":
            arts = [
                {"title": f"a{i}", "publishedAt": f"2024-01-{10 + i:02d}T12:00:00Z"}
                for i in range(10)
            ]
            return (200, {}, json.dumps({"articles": arts, "totalArticles": 25}))
        if page == "2":
            arts = [
                {"title": f"b{i}", "publishedAt": f"2024-01-{20 + i:02d}T12:00:00Z"}
                for i in range(10)
            ]
            return (200, {}, json.dumps({"articles": arts, "totalArticles": 25}))
        return (200, {}, json.dumps({"articles": [], "totalArticles": 25}))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://gnews\.io/api/v4/top-headlines\?"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r1 = client.get("/api/news/top-headlines?max=10&lang=en")
        r2 = client.get("/api/news/top-headlines?max=10&lang=en&page=2")
    assert r1.status_code == 200
    b1 = r1.get_json()
    assert b1["hasMore"] is True
    assert b1["nextPage"] == 2
    assert b1["nextOffset"] == 10
    assert len(b1["items"]) == 10

    assert r2.status_code == 200
    b2 = r2.get_json()
    assert b2["page"] == 2
    assert b2["hasMore"] is True
    assert b2["nextPage"] == 3
    assert len(b2["items"]) == 10

@responses.activate
def test_news_top_headlines_last_page_has_more_false(client):
    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        page = (qs.get("page") or ["1"])[0]
        if page == "3":
            arts = [{"title": "last", "publishedAt": "2024-02-01T00:00:00Z"}]
            return (200, {}, json.dumps({"articles": arts, "totalArticles": 25}))
        return (404, {}, "")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://gnews\.io/api/v4/top-headlines\?"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines?max=10&page=3")
    assert r.status_code == 200
    b = r.get_json()
    assert b["hasMore"] is False
    assert b["nextPage"] is None
    assert b["nextOffset"] is None
    assert len(b["items"]) == 1
    assert b["total"] == 25

@responses.activate
def test_news_top_headlines_offset_instead_of_page(client):
    responses.add(
        responses.GET,
        re.compile(r"https://gnews\.io/api/v4/top-headlines\?"),
        json={"articles": [], "totalArticles": 0},
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines?max=10&offset=10")
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["page"] == ["2"]

@responses.activate
def test_news_top_headlines_invalid_page(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines?page=0")
    assert r.status_code == 400
    assert "page" in r.get_json()["error"].lower()

@responses.activate
def test_news_top_headlines_invalid_max_not_int(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines?max=ten")
    assert r.status_code == 400
    assert "max" in r.get_json()["error"].lower()

@responses.activate
def test_news_top_headlines_offset_not_multiple_of_max(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines?max=20&offset=5")
    assert r.status_code == 400
    assert "offset" in r.get_json()["error"].lower()

@responses.activate
def test_news_top_headlines_page_offset_mismatch(client):
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines?max=10&page=2&offset=0")
    assert r.status_code == 400
    assert "disagree" in r.get_json()["error"].lower()

@responses.activate
def test_news_invalid_upstream_json(client):
    responses.add(
        responses.GET,
        re.compile(r"https://gnews\.io/api/v4/top-headlines\?"),
        body="NOT JSON",
        status=200,
    )
    with patch.dict(os.environ, {"GNEWS_API_KEY": "secret"}):
        r = client.get("/api/news/top-headlines")
    assert r.status_code == 502
    assert r.get_json()["error"] == "Invalid response from GNews API"
