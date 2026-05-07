"""Tests for OpenFEC proxy route (mocked HTTP)."""

import os
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import responses


@responses.activate
def test_fec_candidates_missing_key(client):
    with patch.dict(os.environ, {"OPENFEC_API_KEY": ""}):
        r = client.get("/api/fec/candidates?name=Smith")
    assert r.status_code == 503
    assert r.get_json()["error"] == "Missing OPENFEC_API_KEY"


@responses.activate
def test_fec_candidates_missing_q(client):
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/candidates")
    assert r.status_code == 400
    assert r.get_json()["error"] == "Query parameter 'q' is required (alias: 'name')"


@responses.activate
def test_fec_candidates_forwards_q_and_key(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        json={"results": [], "pagination": {"count": 0, "page": 1, "pages": 0}},
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/v1/names/candidates?q=trump")
    assert r.status_code == 200
    body = r.get_json()
    assert body["results"] == []
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["api_key"] == ["secret"]
    assert qs["q"] == ["trump"]
    assert qs["per_page"] == ["5"]


@responses.activate
def test_fec_legacy_candidates_path_still_works(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        json={"results": [{"name": "X"}], "pagination": {}},
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/candidates?q=a")
    assert r.status_code == 200
    assert r.get_json()["results"] == [{"name": "X"}]


@responses.activate
def test_fec_omitted_per_page_defaults_to_five(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        json={"results": [], "pagination": {}},
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/v1/names/candidates?q=tru&typeahead=1")
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["per_page"] == ["5"]


@responses.activate
def test_fec_typeahead_respects_explicit_per_page(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        json={"results": [], "pagination": {}},
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/v1/names/candidates?q=x&typeahead=true&per_page=25")
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["per_page"] == ["25"]


@responses.activate
def test_fec_candidates_name_alias_maps_to_q(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        json={"results": [], "pagination": {}},
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/candidates?name=Jane%20Doe")
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["q"] == ["Jane Doe"]
    assert qs["per_page"] == ["5"]
    assert "name" not in qs


@responses.activate
def test_fec_candidates_forwards_optional_pagination(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        json={"results": [], "pagination": {}},
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/candidates?q=X&page=2&per_page=5")
    assert r.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["page"] == ["2"]
    assert qs["per_page"] == ["5"]


@responses.activate
def test_fec_candidates_invalid_upstream_json(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.open\.fec\.gov/v1/names/candidates/\?"),
        body="not json",
        status=200,
    )
    with patch.dict(os.environ, {"OPENFEC_API_KEY": "secret"}):
        r = client.get("/api/fec/candidates?q=Y")
    assert r.status_code == 502
    assert r.get_json()["error"] == "Invalid response from OpenFEC API"
