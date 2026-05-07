"""Tests for GET /api/economy/summary (FRED proxy, mocked HTTP)."""

from __future__ import annotations

import json
import os
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
import responses


def _fred_payload(date1: str, val1: str, date2: str, val2: str) -> dict:
    return {
        "observations": [
            {"date": date1, "value": val1},
            {"date": date2, "value": val2},
        ]
    }


def _fred_callback(
    scenarios: dict[str, dict],
    *,
    http_404_series: str | None = None,
    invalid_json_series: str | None = None,
):
    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        if http_404_series and sid == http_404_series:
            return (404, {}, "")
        if invalid_json_series and sid == invalid_json_series:
            return (200, {}, "NOT JSON {")
        body = scenarios.get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    return callback


@responses.activate
def test_economy_summary_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/summary")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["error"] == "Missing FRED_API_KEY"
    assert "hint" in data


@responses.activate
def test_economy_summary_all_tiles_success(client):
    scenarios = {
        "CPIAUCSL": _fred_payload("2024-03-01", "312.332", "2024-02-01", "311.0"),
        "UNRATE": _fred_payload("2024-03-01", "3.9", "2024-02-01", "3.8"),
        "FEDFUNDS": _fred_payload("2024-03-01", "5.33", "2024-02-01", "5.25"),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "as_of" in data
    tiles = data["tiles"]
    assert set(tiles) == {
        "cpi_all_items",
        "unemployment_rate",
        "federal_funds_effective",
    }
    cpi = tiles["cpi_all_items"]
    assert "error" not in cpi
    assert cpi["series_id"] == "CPIAUCSL"
    assert cpi["label"]
    assert cpi["unit"] == "index"
    assert cpi["value"] == 312.332
    assert cpi["observation_date"] == "2024-03-01"
    assert cpi["change"] == pytest.approx(312.332 - 311.0)
    assert cpi["prior_observation_date"] == "2024-02-01"

    un = tiles["unemployment_rate"]
    assert un["series_id"] == "UNRATE"
    assert un["value"] == 3.9
    assert un["change"] == pytest.approx(0.1)


@responses.activate
def test_economy_summary_one_tile_http_error(client):
    scenarios = {
        "CPIAUCSL": _fred_payload("2024-03-01", "312.0", "2024-02-01", "311.0"),
        "UNRATE": _fred_payload("2024-03-01", "3.9", "2024-02-01", "3.8"),
        "FEDFUNDS": _fred_payload("2024-03-01", "5.33", "2024-02-01", "5.25"),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios, http_404_series="UNRATE"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/summary")
    assert resp.status_code == 200
    tiles = resp.get_json()["tiles"]
    assert "error" in tiles["unemployment_rate"]
    assert tiles["unemployment_rate"]["hint"]
    assert tiles["cpi_all_items"]["value"] == 312.0


@responses.activate
def test_economy_summary_one_tile_invalid_json(client):
    scenarios = {
        "CPIAUCSL": _fred_payload("2024-03-01", "312.0", "2024-02-01", "311.0"),
        "UNRATE": _fred_payload("2024-03-01", "3.9", "2024-02-01", "3.8"),
        "FEDFUNDS": _fred_payload("2024-03-01", "5.33", "2024-02-01", "5.25"),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios, invalid_json_series="FEDFUNDS"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/summary")
    assert resp.status_code == 200
    tiles = resp.get_json()["tiles"]
    assert tiles["federal_funds_effective"]["error"] == "Invalid JSON from FRED"
    assert tiles["cpi_all_items"]["value"] == 312.0


@responses.activate
def test_economy_overview_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/overview")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["error"] == "Missing FRED_API_KEY"
    assert "hint" in data


def _overview_obs(dates_values: list[tuple[str, str]]) -> dict:
    return {"observations": [{"date": d, "value": v} for d, v in dates_values]}


@responses.activate
def test_economy_overview_all_sections_success(client):
    # FRED returns sort_order=desc: newest observation first; limit=3 caps rows.
    scenarios = {
        "GDPC1": _overview_obs(
            [
                ("2026-01-01", "23100.0"),
                ("2025-10-01", "23000.0"),
                ("2025-07-01", "22900.0"),
            ]
        ),
        "PCE": _overview_obs(
            [
                ("2026-03-01", "15200.0"),
                ("2025-11-01", "15100.0"),
                ("2025-08-01", "15000.0"),
            ]
        ),
        "UNRATE": _overview_obs(
            [("2026-03-01", "4.0"), ("2025-11-01", "4.1"), ("2025-08-01", "4.2")]
        ),
        "FEDFUNDS": _overview_obs(
            [("2026-03-01", "4.25"), ("2025-12-01", "4.5"), ("2025-09-01", "4.6")]
        ),
        "CPIAUCSL": _overview_obs(
            [("2026-03-01", "322.0"), ("2026-01-01", "320.0"), ("2025-10-01", "318.0")]
        ),
        "CSUSHPISA": _overview_obs(
            [("2026-03-01", "322.1"), ("2025-12-01", "320.5"), ("2025-09-01", "319.0")]
        ),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/overview")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "as_of" in data
    assert "window" not in data
    sections = data["sections"]
    assert set(sections) == {
        "gdp",
        "consumer_spending",
        "labor",
        "interest_rates",
        "inflation",
        "housing",
    }
    gdp = sections["gdp"]
    assert "error" not in gdp
    assert gdp["series_id"] == "GDPC1"
    assert len(gdp["observations"]) == 3
    assert gdp["observations"][0]["value"] == 23100.0
    assert gdp["observations"][1]["value"] == 23000.0
    assert gdp["observations"][2]["value"] == 22900.0


@responses.activate
def test_economy_overview_one_series_http_error(client):
    scenarios = {
        "GDPC1": _overview_obs([("2026-01-01", "1")]),
        "PCE": _overview_obs([("2026-01-01", "1")]),
        "UNRATE": _overview_obs([("2026-01-01", "1")]),
        "FEDFUNDS": _overview_obs([("2026-01-01", "1")]),
        "CPIAUCSL": _overview_obs([("2026-01-01", "1")]),
        "CSUSHPISA": _overview_obs([("2026-01-01", "1")]),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios, http_404_series="GDPC1"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/overview")
    assert resp.status_code == 200
    sections = resp.get_json()["sections"]
    assert "error" in sections["gdp"]
    assert sections["labor"]["series_id"] == "UNRATE"
