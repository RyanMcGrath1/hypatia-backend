"""Tests for economy FRED routes (mocked HTTP)."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses


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
def test_economy_overview_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/dashboard")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["error"] == "Missing FRED_API_KEY"
    assert "hint" in data


def test_economy_overview_path_returns_404(client):
    resp = client.get("/api/economy/overview")
    assert resp.status_code == 404


def test_economy_sector_dashboard_unknown_sector_returns_404(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/not-a-sector/dashboard")
    assert resp.status_code == 404
    assert "unknown" in resp.get_json().get("error", "").lower()


@responses.activate
def test_economy_sector_dashboard_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/labor/dashboard")
    assert resp.status_code == 503


@responses.activate
@patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
def test_economy_sector_dashboard_labor_only_fetches_unrate(_mock_today, client):
    scenarios = {
        "UNRATE": _overview_obs(
            [
                ("2026-03-01", "4.0"),
                ("2026-02-01", "4.15"),
                ("2025-11-01", "4.1"),
                ("2025-08-01", "4.2"),
            ]
        ),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/labor/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["observation_start"] == "2026-01-01"
    assert data["observation_end"] == "2026-06-01"
    assert set(data["sections"]) == {"labor"}
    lab = data["sections"]["labor"]
    assert lab["series_id"] == "UNRATE"
    assert len(lab["observations"]) == 2
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs.get("observation_start") == ["2026-01-01"]
    assert qs.get("observation_end") == ["2026-06-01"]


@responses.activate
@patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
def test_economy_sector_dashboard_rates_alias_maps_to_interest_rates(_mock_today, client):
    scenarios = {
        "FEDFUNDS": _overview_obs([("2026-03-01", "4.25"), ("2025-12-01", "4.5")]),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/rates/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data["sections"]) == {"interest_rates"}
    assert data["sections"]["interest_rates"]["series_id"] == "FEDFUNDS"
    assert len(data["sections"]["interest_rates"]["observations"]) == 1


def test_economy_sector_dashboard_invalid_observation_start(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/dashboard?observation_start=not-a-date")
    assert resp.status_code == 400


def test_economy_sector_dashboard_start_after_end_returns_400(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get(
            "/api/economy/gdp/dashboard?observation_start=2025-06-01&observation_end=2025-01-01"
        )
    assert resp.status_code == 400


@responses.activate
def test_economy_sector_dashboard_custom_range_forwarded_to_fred(client):
    scenarios = {
        "GDPC1": _overview_obs(
            [
                ("2025-06-01", "23050.0"),
                ("2025-03-01", "23000.0"),
                ("2024-12-01", "22900.0"),
            ]
        ),
    }

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        assert qs.get("observation_start") == ["2025-01-01"]
        assert qs.get("observation_end") == ["2025-06-30"]
        return _fred_callback(scenarios)(request)

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get(
            "/api/economy/gdp/dashboard?observation_start=2025-01-01&observation_end=2025-06-30"
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["observation_start"] == "2025-01-01"
    assert data["observation_end"] == "2025-06-30"
    gdp = data["sections"]["gdp"]
    assert len(gdp["observations"]) == 2


def test_economy_sector_dashboard_invalid_observation_end(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/dashboard?observation_end=bad")
    assert resp.status_code == 400


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
        # Consecutive CPI months so calendar MoM resolves (was sparse gaps → null MoM).
        "CPIAUCSL": _overview_obs(
            [("2026-03-01", "322.0"), ("2026-02-01", "320.0"), ("2026-01-01", "318.0")]
        ),
        "CSUSHPISA": _overview_obs(
            [("2026-03-01", "322.1"), ("2025-12-01", "320.5"), ("2025-09-01", "319.0")]
        ),
        "VIXCLS": _overview_obs(
            [("2026-07-21", "17.05"), ("2026-06-20", "16.65"), ("2026-05-20", "15.80")]
        ),
        "CFNAIMA3": _overview_obs([("2026-05-01", "0.03"), ("2026-04-01", "0.02")]),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/dashboard")
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

    inf = sections["inflation"]
    assert inf["momInflation"] == inf["observations"][0]["momInflation"]
    assert inf["yoyInflation"] is None
    assert inf["observations"][0]["momInflation"] == pytest.approx(0.62)
    assert inf["observations"][0]["yoyInflation"] is None
    assert inf["observations"][0]["acceleration"] == "decelerating"

    sentiment = data["sentiment"]
    assert sentiment["is_live"] is True
    assert sentiment["period_label"] == "MACRO INDEX"
    assert 0 <= sentiment["score"] <= 100
    assert sentiment["volatility_pct"] == pytest.approx(8.1, abs=0.2)
    assert sentiment["stability"] == pytest.approx(51.05, abs=0.1)
    assert sentiment["trend"] in {"up", "down", "flat"}
    assert sentiment["status_label"] in {"OPTIMAL", "STEADY", "WEAK"}


def test_economy_overview_invalid_observation_end(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/dashboard?observation_end=not-a-date")
    assert resp.status_code == 400
    assert "observation_end" in resp.get_json().get("error", "").lower()


@responses.activate
def test_economy_overview_observation_end_forwarded_and_echoed(client):
    scenarios = {
        "GDPC1": _overview_obs([("2025-11-01", "1")]),
        "PCE": _overview_obs([("2025-11-01", "1")]),
        "UNRATE": _overview_obs([("2025-11-01", "1")]),
        "FEDFUNDS": _overview_obs([("2025-11-01", "1")]),
        # Three levels so acceleration compares Nov MoM vs Oct MoM (needs Sep as prior for Oct).
        "CPIAUCSL": _overview_obs(
            [
                ("2025-11-01", "300"),
                ("2025-10-01", "299"),
                ("2025-09-01", "298"),
            ]
        ),
        "CSUSHPISA": _overview_obs([("2025-11-01", "1")]),
    }
    checked = {"n": 0}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        assert qs.get("observation_end") == ["2025-11-01"]
        checked["n"] += 1
        return _fred_callback(scenarios)(request)

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/dashboard?observation_end=2025-11-01")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("observation_end") == "2025-11-01"
    assert checked["n"] >= 1
    inf = data["sections"]["inflation"]
    assert inf["acceleration"] == "decelerating"
    assert inf["acceleration"] == inf["observations"][0]["acceleration"]


def _month_series_descending(base: date, n: int, cpi_start: int) -> list[tuple[str, str]]:
    """Newest-first monthly ISO dates with CPI levels cpi_start, cpi_start-1, ..."""
    rows: list[tuple[str, str]] = []

    def add_months(d: date, delta: int) -> date:
        idx = d.year * 12 + (d.month - 1) + delta
        y, m0 = divmod(idx, 12)
        return date(y, m0 + 1, 1)

    for i in range(n):
        dt = add_months(base, -i)
        rows.append((dt.isoformat(), str(cpi_start - i)))
    return rows


@responses.activate
def test_economy_overview_inflation_cpi_enrichment_yoy_and_section_headlines(client):
    """CPI overview requests extra FRED rows so YoY exists for each displayed month."""
    cpi_rows = _month_series_descending(date(2027, 1, 1), 22, 300)
    scenarios = {
        "GDPC1": _overview_obs([("2026-01-01", "1")]),
        "PCE": _overview_obs([("2026-01-01", "1")]),
        "UNRATE": _overview_obs([("2026-01-01", "1")]),
        "FEDFUNDS": _overview_obs([("2026-01-01", "1")]),
        "CPIAUCSL": _overview_obs(cpi_rows),
        "CSUSHPISA": _overview_obs([("2026-01-01", "1")]),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/dashboard")
    assert resp.status_code == 200
    inf = resp.get_json()["sections"]["inflation"]
    assert inf["series_id"] == "CPIAUCSL"
    assert len(inf["observations"]) == 10

    # Newest CPI 300 vs prior month 299 → (300-299)/299*100
    assert inf["momInflation"] == pytest.approx(0.33)
    assert inf["observations"][0]["momInflation"] == pytest.approx(0.33)
    # YoY: 300 vs 288 at index 12
    assert inf["yoyInflation"] == pytest.approx(4.17)
    assert inf["observations"][0]["yoyInflation"] == pytest.approx(4.17)

    assert inf["observations"][0]["acceleration"] == "decelerating"

    assert inf["observations"][-1]["yoyInflation"] is not None
    assert inf["observations"][-1]["momInflation"] is not None


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
        resp = client.get("/api/economy/dashboard")
    assert resp.status_code == 200
    sections = resp.get_json()["sections"]
    assert "error" in sections["gdp"]
    assert sections["labor"]["series_id"] == "UNRATE"


_EMPLOYMENT_SECTOR_IDS = (
    "PAYEMS",
    "USPRIV",
    "USGOOD",
    "SRVPRD",
    "USPBS",
    "USEHS",
    "USLAH",
    "USTRADE",
    "MANEMP",
    "USFIRE",
    "USCONS",
    "USINFO",
    "USGOVT",
    "CES4300000001",
    "USWTRADE",
    "USMINE",
)


def _employment_scenarios(value_by_series: dict[str, str] | None = None) -> dict:
    value_by_series = value_by_series or {}
    return {
        sid: {
            "observations": [
                {"date": "2026-04-01", "value": value_by_series.get(sid, "100")},
                {"date": "2026-05-01", "value": value_by_series.get(sid, "101")},
            ]
        }
        for sid in _EMPLOYMENT_SECTOR_IDS
    }


def test_economy_labor_sector_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_labor_sector_all_series_success(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_employment_scenarios()),
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "test_key"}),
        patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start_date"] == "2026-01-01"
    assert data["end_date"] == "2026-05-18"
    series_ids = [s["id"] for s in data["series"]]
    assert series_ids == list(_EMPLOYMENT_SECTOR_IDS)
    payems = data["series"][0]
    assert payems["name"] == "Total Nonfarm Payrolls"
    assert "error" not in payems
    assert payems["observations"][0] == {"date": "2026-04-01", "value": "100"}


@responses.activate
def test_economy_labor_sector_forwards_observation_start_and_api_key(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_employment_scenarios()),
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "secret-key"}),
        patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    assert len(responses.calls) == len(_EMPLOYMENT_SECTOR_IDS)
    for call in responses.calls:
        qs = parse_qs(urlparse(call.request.url).query)
        assert qs["api_key"] == ["secret-key"]
        assert qs["file_type"] == ["json"]
        assert qs["observation_start"] == ["2026-01-01"]
        assert qs["observation_end"] == ["2026-05-18"]
        assert qs["series_id"][0] in _EMPLOYMENT_SECTOR_IDS


@responses.activate
def test_economy_labor_sector_custom_observation_window(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_employment_scenarios()),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get(
            "/api/economy/labor/sector?observation_start=2024-06-01&observation_end=2025-12-31"
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start_date"] == "2024-06-01"
    assert data["end_date"] == "2025-12-31"
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["observation_start"] == ["2024-06-01"]
    assert qs["observation_end"] == ["2025-12-31"]


@responses.activate
def test_economy_labor_sector_one_series_http_404_partial(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_employment_scenarios(), http_404_series="MANEMP"),
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "k"}),
        patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.get_json()["series"]}
    assert by_id["MANEMP"]["error"] == "FRED returned HTTP 404"
    assert by_id["MANEMP"]["observations"] == []
    assert "error" not in by_id["PAYEMS"]


@responses.activate
def test_economy_labor_sector_cleans_missing_value_to_null(client):
    scenarios = {
        sid: {
            "observations": [
                {"date": "2026-04-01", "value": "."},
                {"date": "2026-05-01", "value": "101"},
            ]
        }
        for sid in _EMPLOYMENT_SECTOR_IDS
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "k"}),
        patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    payems = next(s for s in resp.get_json()["series"] if s["id"] == "PAYEMS")["observations"]
    assert payems[0] == {"date": "2026-04-01", "value": None}
    assert payems[1] == {"date": "2026-05-01", "value": "101"}


_LABOR_EARNINGS_INFLATION_IDS = ("CES0500000003", "CPIAUCSL")


def _earnings_inflation_scenarios() -> dict:
    return {
        sid: {
            "observations": [
                {"date": "2026-04-01", "value": "35.50" if sid == "CES0500000003" else "320.0"},
                {"date": "2026-05-01", "value": "35.75" if sid == "CES0500000003" else "322.0"},
            ]
        }
        for sid in _LABOR_EARNINGS_INFLATION_IDS
    }


@responses.activate
def test_economy_labor_earnings_inflation_success(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_earnings_inflation_scenarios()),
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "test_key"}),
        patch(
            "hypatia.services.economy.core._sector_dashboard_clock_today",
            return_value=fixed_today,
        ),
    ):
        resp = client.get("/api/economy/labor/earnings-inflation")
    assert resp.status_code == 200
    data = resp.get_json()
    assert [s["id"] for s in data["series"]] == list(_LABOR_EARNINGS_INFLATION_IDS)
    by_id = {s["id"]: s for s in data["series"]}
    assert by_id["CES0500000003"]["name"] == "Average Hourly Earnings"
    assert by_id["CPIAUCSL"]["name"] == "CPI Inflation"


@responses.activate
def test_economy_labor_earnings_inflation_one_series_fails(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(
            _earnings_inflation_scenarios(),
            http_404_series="CES0500000003",
        ),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/labor/earnings-inflation")
    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.get_json()["series"]}
    assert "error" in by_id["CES0500000003"]
    assert "error" not in by_id["CPIAUCSL"]


_LABOR_AGE_METRIC_FRED_IDS = (
    "LNS14000012",
    "LNS14000036",
    "LNS14000060",
    "LNS14024230",
    "LNS11300012",
    "LNS11300036",
    "LNS11300060",
    "LNS11324230",
    "LNS12300012",
    "LNS12300060",
    # 20-24 and 55+ emp-pop ratios are derived from level series (not on FRED).
    "LNS12000036",
    "LNU00000036",
    "LNS12024230",
    "LNU00024230",
)


def _labor_age_metrics_scenarios() -> dict:
    scenarios = {
        sid: {
            "observations": [
                {"date": "2026-04-01", "value": "5.0"},
                {"date": "2026-05-01", "value": "5.1"},
            ]
        }
        for sid in _LABOR_AGE_METRIC_FRED_IDS
    }
    # Derived 55+ emp-pop: 37810 / 105140 * 100 ≈ 36.0
    scenarios["LNS12024230"]["observations"] = [{"date": "2026-04-01", "value": "37810"}]
    scenarios["LNU00024230"]["observations"] = [{"date": "2026-04-01", "value": "105140"}]
    return scenarios


@responses.activate
def test_economy_labor_age_metrics_success(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_labor_age_metrics_scenarios()),
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "test_key"}),
        patch(
            "hypatia.services.economy.core._sector_dashboard_clock_today",
            return_value=fixed_today,
        ),
    ):
        resp = client.get("/api/economy/labor/age-metrics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start_date"] == "2026-01-01"
    assert data["end_date"] == "2026-05-18"
    assert [m["id"] for m in data["metrics"]] == [
        "unemployment_rate",
        "labor_force_participation",
        "employment_population_ratio",
    ]
    unemployment = data["metrics"][0]
    assert unemployment["name"] == "Unemployment Rate"
    assert [s["age_group"] for s in unemployment["series"]] == ["16-19", "20-24", "25-54", "55+"]
    assert unemployment["series"][0]["id"] == "LNS14000012"
    assert unemployment["series"][0]["observations"][0] == {"date": "2026-04-01", "value": "5.0"}
    emp_pop = next(m for m in data["metrics"] if m["id"] == "employment_population_ratio")
    ratio_55 = next(s for s in emp_pop["series"] if s["age_group"] == "55+")
    assert ratio_55["id"] == "LNS12324230"
    assert "error" not in ratio_55
    assert len(responses.calls) == len(_LABOR_AGE_METRIC_FRED_IDS)


@responses.activate
def test_economy_labor_age_metrics_custom_window(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_labor_age_metrics_scenarios()),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get(
            "/api/economy/labor/age-metrics?observation_start=2024-06-01&observation_end=2025-12-31"
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start_date"] == "2024-06-01"
    assert data["end_date"] == "2025-12-31"
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["observation_start"] == ["2024-06-01"]
    assert qs["observation_end"] == ["2025-12-31"]


@responses.activate
def test_economy_labor_age_metrics_one_series_fails(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(
            _labor_age_metrics_scenarios(),
            http_404_series="LNS14000012",
        ),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/labor/age-metrics")
    assert resp.status_code == 200
    unemployment = resp.get_json()["metrics"][0]["series"]
    by_id = {s["id"]: s for s in unemployment}
    assert by_id["LNS14000012"]["error"] == "FRED returned HTTP 404"
    assert "error" not in by_id["LNS14000036"]


@responses.activate
def test_economy_labor_age_metrics_derives_emp_pop_55_plus(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_labor_age_metrics_scenarios()),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/labor/age-metrics")
    emp_pop = next(m for m in resp.get_json()["metrics"] if m["id"] == "employment_population_ratio")
    ratio_55 = next(s for s in emp_pop["series"] if s["age_group"] == "55+")
    assert ratio_55["observations"][0] == {"date": "2026-04-01", "value": "36.0"}


def test_economy_labor_sector_returns_503_when_all_network_failed(client):
    empty_payload = {
        "start_date": "2026-01-01",
        "end_date": "2026-05-18",
        "series": [],
    }
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "k"}),
        patch(
            "hypatia.routes.economy.labor_sector.build_employment_sectors",
            return_value=(empty_payload, True),
        ),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


@responses.activate
def test_fred_observations_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get(
            "/api/economy/fred/observations?series_id=PAYEMS&observation_start=2020-01-01"
        )
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


def test_fred_observations_missing_series_id(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "secret"}):
        resp = client.get("/api/economy/fred/observations?observation_start=2020-01-01")
    assert resp.status_code == 400
    assert "series_id" in resp.get_json()["error"]


@responses.activate
def test_fred_observations_optional_observation_start_forwards_desc(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations\?"),
        json={"observations": [{"date": "2024-06-01", "value": "2"}], "count": 1},
        status=200,
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "myfredkey"}):
        resp = client.get(
            "/api/economy/fred/observations?series_id=PAYEMS&limit=72&sort_order=desc"
        )
    assert resp.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert "observation_start" not in qs
    assert qs["sort_order"] == ["desc"]
    assert qs["limit"] == ["72"]


def test_fred_observations_invalid_limit(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "secret"}):
        resp = client.get(
            "/api/economy/fred/observations?series_id=PAYEMS&observation_start=2020-01-01"
            "&limit=notint"
        )
    assert resp.status_code == 400


@responses.activate
def test_fred_observations_forwards_params_and_returns_upstream_body(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations\?"),
        json={"observations": [{"date": "2020-01-01", "value": "1"}], "count": 1},
        status=200,
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "myfredkey"}):
        resp = client.get(
            "/api/economy/fred/observations?series_id=PAYEMS&observation_start=2020-01-01"
        )
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["api_key"] == ["myfredkey"]
    assert qs["file_type"] == ["json"]
    assert qs["series_id"] == ["PAYEMS"]
    assert qs["observation_start"] == ["2020-01-01"]
    assert qs["limit"] == ["60"]


@responses.activate
def test_fred_observations_invalid_upstream_json(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations\?"),
        body="{not json",
        status=200,
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get(
            "/api/economy/fred/observations?series_id=PAYEMS&observation_start=2020-01-01"
        )
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "Invalid response from FRED API"


@responses.activate
def test_payems_delta_series_forwards_units_and_sort_order(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations\?"),
        json={"observations": [{"date": "2026-03-01", "value": "178"}], "count": 1},
        status=200,
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "myfredkey"}):
        resp = client.get("/api/economy/fred/series/PAYEMS/delta?limit=72&sort_order=desc")
    assert resp.status_code == 200
    qs = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert qs["api_key"] == ["myfredkey"]
    assert qs["file_type"] == ["json"]
    assert qs["series_id"] == ["PAYEMS"]
    assert qs["units"] == ["chg"]
    assert qs["sort_order"] == ["desc"]
    assert qs["limit"] == ["72"]


def test_economy_detail_missing_topic_returns_400(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/detail")
    assert resp.status_code == 400


def test_economy_detail_unknown_topic_returns_404(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/detail?topic=widgets")
    assert resp.status_code == 404


@responses.activate
@patch("hypatia.services.economy.core._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
def test_economy_detail_labor_returns_charts_and_headline(_mock_today, client):
    scenarios = {
        "UNRATE": _overview_obs(
            [
                ("2026-03-01", "4.0"),
                ("2026-02-01", "4.15"),
            ]
        ),
    }
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(scenarios),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/detail?topic=labor")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["topic"] == "labor"
    assert len(data["charts"]) == 1
    assert data["charts"][0]["key"] == "labor"
    assert data["charts"][0]["series_id"] == "UNRATE"
    assert data["headline"]["value"] == 4.0
    assert data["headline"]["observation_date"] == "2026-03-01"


def test_economy_cpi_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/cpi")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_cpi_returns_last_five_months(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        captured["series_id"] = qs.get("series_id", [])
        captured["limit"] = qs.get("limit", [])
        captured["sort_order"] = qs.get("sort_order", [])
        body = {
            "observations": [
                {"date": "2026-05-01", "value": "322.1"},
                {"date": "2026-04-01", "value": "321.0"},
                {"date": "2026-03-01", "value": "319.8"},
                {"date": "2026-02-01", "value": "318.5"},
                {"date": "2026-01-01", "value": "317.2"},
            ]
        }
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/cpi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert captured["series_id"] == ["CPIAUCSL"]
    assert captured["limit"] == ["5"]
    assert captured["sort_order"] == ["desc"]
    assert data["series_id"] == "CPIAUCSL"
    assert data["unit"] == "index"
    assert "as_of" in data
    assert len(data["observations"]) == 5
    assert data["observations"][0] == {"date": "2026-05-01", "value": 322.1}
    assert data["observations"][-1] == {"date": "2026-01-01", "value": 317.2}


@responses.activate
def test_economy_cpi_fred_http_error(client):
    responses.add(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        json={"error_message": "Too Many Requests.  Exceeded Rate Limit"},
        status=429,
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/cpi")
    assert resp.status_code == 429
    assert "Too Many Requests" in resp.get_json()["error"]


_PCE_VS_TARGET_IDS = ("PCEPI", "PCEPILFE")


def _pce_vs_target_scenarios() -> dict:
    return {
        "PCEPI": {"observations": [{"date": "2026-05-01", "value": "2.40"}]},
        "PCEPILFE": {"observations": [{"date": "2026-05-01", "value": "2.80"}]},
    }


@responses.activate
def test_economy_inflation_pce_vs_target_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/inflation/pce-vs-target")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_inflation_pce_vs_target_success(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("units", []).append((qs.get("units") or [""])[0])
        captured.setdefault("sort_order", []).append((qs.get("sort_order") or [""])[0])
        captured.setdefault("limit", []).append((qs.get("limit") or [""])[0])
        body = _pce_vs_target_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/inflation/pce-vs-target")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(captured["series_id"]) == set(_PCE_VS_TARGET_IDS)
    assert captured["units"] == ["pc1", "pc1"]
    assert captured["sort_order"] == ["desc", "desc"]
    assert captured["limit"] == ["2", "2"]
    assert data["target"] == 2.0
    assert "as_of" in data
    assert data["headline"] == {
        "series_id": "PCEPI",
        "label": "PCE Headline",
        "value": 2.4,
        "observation_date": "2026-05-01",
    }
    assert data["core"] == {
        "series_id": "PCEPILFE",
        "label": "Core PCE",
        "value": 2.8,
        "observation_date": "2026-05-01",
    }


@responses.activate
def test_economy_inflation_pce_vs_target_one_series_fails(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_pce_vs_target_scenarios(), http_404_series="PCEPI"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/inflation/pce-vs-target")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["headline"]["value"] is None
    assert "error" in data["headline"]
    assert data["core"]["value"] == 2.8


@responses.activate
def test_economy_inflation_pce_vs_target_all_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/inflation/pce-vs-target")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


_FED_FUNDS_TARGET_IDS = ("DFEDTARL", "DFEDTARU")


def _fed_funds_target_scenarios() -> dict:
    return {
        sid: {
            "observations": [
                {"date": "2026-01-15", "value": "4.25" if sid == "DFEDTARU" else "4.00"},
                {"date": "2026-03-01", "value": "4.00" if sid == "DFEDTARU" else "3.75"},
                {"date": "2026-05-01", "value": "3.75" if sid == "DFEDTARU" else "3.50"},
            ]
        }
        for sid in _FED_FUNDS_TARGET_IDS
    }


@responses.activate
def test_economy_rates_fed_funds_target_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/rates/fed-funds-target")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_rates_fed_funds_target_success(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("observation_start", []).append(
            (qs.get("observation_start") or [""])[0]
        )
        captured.setdefault("observation_end", []).append((qs.get("observation_end") or [""])[0])
        body = _fed_funds_target_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    fixed_today = date(2026, 5, 18)
    with (
        patch.dict(os.environ, {"FRED_API_KEY": "test_key"}),
        patch(
            "hypatia.services.economy.core._sector_dashboard_clock_today",
            return_value=fixed_today,
        ),
    ):
        resp = client.get("/api/economy/rates/fed-funds-target")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(captured["series_id"]) == set(_FED_FUNDS_TARGET_IDS)
    assert captured["observation_start"] == ["2026-01-01", "2026-01-01"]
    assert captured["observation_end"] == ["2026-05-18", "2026-05-18"]
    assert [s["id"] for s in data["series"]] == list(_FED_FUNDS_TARGET_IDS)
    assert data["start_date"] == "2026-01-01"
    assert data["end_date"] == "2026-05-18"
    assert data["target_lower"] == 3.5
    assert data["target_upper"] == 3.75
    assert data["observation_date"] == "2026-05-01"
    assert "as_of" in data


@responses.activate
def test_economy_rates_fed_funds_target_custom_range(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("observation_start", []).append(
            (qs.get("observation_start") or [""])[0]
        )
        captured.setdefault("observation_end", []).append((qs.get("observation_end") or [""])[0])
        body = _fed_funds_target_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get(
            "/api/economy/rates/fed-funds-target"
            "?observation_start=2026-03-01&observation_end=2026-04-30"
        )
    assert resp.status_code == 200
    assert captured["observation_start"] == ["2026-03-01", "2026-03-01"]
    assert captured["observation_end"] == ["2026-04-30", "2026-04-30"]
    data = resp.get_json()
    assert data["target_lower"] == 3.75
    assert data["target_upper"] == 4.0
    assert data["observation_date"] == "2026-03-01"


@responses.activate
def test_economy_rates_fed_funds_target_one_series_fails(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_fed_funds_target_scenarios(), http_404_series="DFEDTARL"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/rates/fed-funds-target")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["target_lower"] is None
    assert data["target_upper"] is None
    assert data["observation_date"] is None
    by_id = {s["id"]: s for s in data["series"]}
    assert "error" in by_id["DFEDTARL"]
    assert "error" not in by_id["DFEDTARU"]


@responses.activate
def test_economy_rates_fed_funds_target_all_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/rates/fed-funds-target")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


_RATES_KEY_METRICS_IDS = ("DGS10", "MORTGAGE30US", "DGS2")


def _rates_key_metrics_scenarios() -> dict:
    return {
        "DGS10": {"observations": [{"date": "2026-07-17", "value": "4.25"}]},
        "MORTGAGE30US": {"observations": [{"date": "2026-07-10", "value": "6.81"}]},
        "DGS2": {"observations": [{"date": "2026-07-17", "value": "4.72"}]},
    }


@responses.activate
def test_economy_rates_key_metrics_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/rates/key-metrics")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_rates_key_metrics_success(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("sort_order", []).append((qs.get("sort_order") or [""])[0])
        captured.setdefault("limit", []).append((qs.get("limit") or [""])[0])
        body = _rates_key_metrics_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/rates/key-metrics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(captured["series_id"]) == set(_RATES_KEY_METRICS_IDS)
    assert captured["sort_order"] == ["desc", "desc", "desc"]
    assert captured["limit"] == ["1", "1", "1"]
    assert "as_of" in data
    assert [m["series_id"] for m in data["metrics"]] == list(_RATES_KEY_METRICS_IDS)
    by_id = {m["series_id"]: m for m in data["metrics"]}
    assert by_id["DGS10"] == {
        "series_id": "DGS10",
        "label": "10Y Treasury",
        "note": "Benchmark long rate",
        "value": 4.25,
        "observation_date": "2026-07-17",
    }
    assert by_id["MORTGAGE30US"]["value"] == 6.81
    assert by_id["DGS2"]["value"] == 4.72


@responses.activate
def test_economy_rates_key_metrics_one_series_fails(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_rates_key_metrics_scenarios(), http_404_series="DGS10"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/rates/key-metrics")
    assert resp.status_code == 200
    by_id = {m["series_id"]: m for m in resp.get_json()["metrics"]}
    assert by_id["DGS10"]["value"] is None
    assert "error" in by_id["DGS10"]
    assert by_id["DGS2"]["value"] == 4.72


@responses.activate
def test_economy_rates_key_metrics_all_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/rates/key-metrics")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


_CPI_COMPONENTS_IDS = (
    "CPIAUCSL",
    "CUSR0000SAH1",
    "CPIUFDSL",
    "CPIENGSL",
    "CUSR0000SACL1E",
    "CUSR0000SASLE",
)


def _cpi_components_scenarios() -> dict:
    return {
        "CPIAUCSL": {
            "observations": [
                {"date": "2026-06-01", "value": "3.50"},
                {"date": "2026-05-01", "value": "3.20"},
            ]
        },
        "CUSR0000SAH1": {
            "observations": [
                {"date": "2026-06-01", "value": "3.30"},
                {"date": "2026-05-01", "value": "3.10"},
            ]
        },
        "CPIUFDSL": {"observations": [{"date": "2026-06-01", "value": "3.00"}]},
        "CPIENGSL": {"observations": [{"date": "2026-06-01", "value": "15.70"}]},
        "CUSR0000SACL1E": {"observations": [{"date": "2026-06-01", "value": "0.80"}]},
        "CUSR0000SASLE": {"observations": [{"date": "2026-06-01", "value": "3.20"}]},
    }


@responses.activate
def test_economy_inflation_cpi_components_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/inflation/cpi-components")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_inflation_cpi_components_success(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("units", []).append((qs.get("units") or [""])[0])
        captured.setdefault("sort_order", []).append((qs.get("sort_order") or [""])[0])
        captured.setdefault("limit", []).append((qs.get("limit") or [""])[0])
        body = _cpi_components_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/inflation/cpi-components")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(captured["series_id"]) == set(_CPI_COMPONENTS_IDS)
    assert captured["units"] == ["pc1"] * len(_CPI_COMPONENTS_IDS)
    assert captured["sort_order"] == ["desc"] * len(_CPI_COMPONENTS_IDS)
    assert captured["limit"] == ["2"] * len(_CPI_COMPONENTS_IDS)
    assert data["observation_date"] == "2026-06-01"
    assert data["headline"] == {
        "series_id": "CPIAUCSL",
        "label": "Headline CPI",
        "value": 3.5,
        "observation_date": "2026-06-01",
        "previous_value": 3.2,
        "previous_observation_date": "2026-05-01",
        "delta": 0.3,
    }
    assert [c["key"] for c in data["components"]] == [
        "shelter",
        "food",
        "energy",
        "core_goods",
        "core_services",
    ]
    by_key = {c["key"]: c for c in data["components"]}
    assert by_key["shelter"]["includes_in"] == ["core_services"]
    assert by_key["shelter"]["value"] == 3.3
    assert by_key["shelter"]["previous_value"] == 3.1
    assert by_key["shelter"]["delta"] == 0.2
    assert by_key["food"]["value"] == 3.0
    assert by_key["food"]["previous_value"] is None
    assert by_key["food"]["delta"] is None
    assert by_key["energy"]["value"] == 15.7
    assert by_key["core_goods"]["value"] == 0.8
    assert by_key["core_services"]["value"] == 3.2
    assert "includes_in" not in by_key["food"]


@responses.activate
def test_economy_inflation_cpi_components_one_series_fails(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_cpi_components_scenarios(), http_404_series="CPIENGSL"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/inflation/cpi-components")
    assert resp.status_code == 200
    data = resp.get_json()
    by_key = {c["key"]: c for c in data["components"]}
    assert by_key["energy"]["value"] is None
    assert "error" in by_key["energy"]
    assert data["headline"]["value"] == 3.5


@responses.activate
def test_economy_inflation_cpi_components_all_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/inflation/cpi-components")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


_GDP_GROWTH_SERIES_ID = "A191RL1Q225SBEA"


def _gdp_growth_scenarios() -> dict:
    return {
        _GDP_GROWTH_SERIES_ID: _overview_obs(
            [
                ("2025-01-01", "-0.6"),
                ("2025-04-01", "3.8"),
                ("2025-07-01", "4.4"),
                ("2025-10-01", "0.5"),
                ("2026-01-01", "2.1"),
            ]
        ),
    }


@responses.activate
def test_economy_gdp_growth_rate_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/gdp/growth-rate")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
@patch("hypatia.services.economy.detail._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
def test_economy_gdp_growth_rate_success(_mock_today, client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("observation_start", []).append(
            (qs.get("observation_start") or [""])[0]
        )
        captured.setdefault("observation_end", []).append((qs.get("observation_end") or [""])[0])
        body = _gdp_growth_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/gdp/growth-rate")
    assert resp.status_code == 200
    data = resp.get_json()
    assert captured["series_id"] == [_GDP_GROWTH_SERIES_ID]
    assert captured["observation_start"] == ["2021-01-01"]
    assert captured["observation_end"] == ["2026-06-01"]
    assert data["series_id"] == _GDP_GROWTH_SERIES_ID
    assert data["value"] == 2.1
    assert data["observation_date"] == "2026-01-01"
    assert len(data["observations"]) == 5
    assert data["observations"][0] == {"date": "2026-01-01", "value": 2.1}
    assert data["observations"][-1] == {"date": "2025-01-01", "value": -0.6}


@responses.activate
@patch("hypatia.services.economy.detail._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
def test_economy_gdp_growth_rate_custom_window(_mock_today, client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_gdp_growth_scenarios()),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get(
            "/api/economy/gdp/growth-rate?observation_start=2025-01-01&observation_end=2026-01-01"
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start_date"] == "2025-01-01"
    assert data["end_date"] == "2026-01-01"
    assert len(data["observations"]) == 5


@responses.activate
def test_economy_gdp_growth_rate_invalid_window(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get(
            "/api/economy/gdp/growth-rate?observation_start=2026-06-01&observation_end=2025-01-01"
        )
    assert resp.status_code == 400


@responses.activate
def test_economy_gdp_growth_rate_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/growth-rate")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


_GDP_SECTOR_SERIES = ("GDPC1", "RVASPI", "RVAMA", "RVAAFH")


def _gdp_sector_contribution_scenarios() -> dict:
    return {
        "GDPC1": _overview_obs([("2026-01-01", "25000.0")]),
        "RVASPI": _overview_obs([("2026-01-01", "17000.0")]),
        "RVAMA": _overview_obs([("2026-01-01", "4500.0")]),
        "RVAAFH": _overview_obs([("2026-01-01", "2500.0")]),
    }


@responses.activate
def test_economy_gdp_sector_contribution_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/gdp/sector-contribution")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_gdp_sector_contribution_success(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("sort_order", []).append((qs.get("sort_order") or [""])[0])
        captured.setdefault("limit", []).append((qs.get("limit") or [""])[0])
        body = _gdp_sector_contribution_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/gdp/sector-contribution")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(captured["series_id"]) == set(_GDP_SECTOR_SERIES)
    assert captured["sort_order"] == ["desc"] * len(_GDP_SECTOR_SERIES)
    assert captured["limit"] == ["1"] * len(_GDP_SECTOR_SERIES)
    assert data["gdp_series_id"] == "GDPC1"
    assert data["observation_date"] == "2026-01-01"
    assert data["unit"] == "percent of real GDP"
    sectors = {row["key"]: row for row in data["sectors"]}
    assert sectors["services"]["value"] == 68.0
    assert sectors["manufacturing"]["value"] == 18.0
    assert sectors["agriculture"]["value"] == 10.0
    assert sectors["services"]["series_id"] == "RVASPI"
    assert sectors["manufacturing"]["label"] == "Manufacturing"


@responses.activate
def test_economy_gdp_sector_contribution_one_series_failed(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_gdp_sector_contribution_scenarios(), http_404_series="RVAMA"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/sector-contribution")
    assert resp.status_code == 200
    sectors = {row["key"]: row for row in resp.get_json()["sectors"]}
    assert sectors["manufacturing"]["value"] is None
    assert "error" in sectors["manufacturing"]
    assert sectors["services"]["value"] == 68.0


@responses.activate
def test_economy_gdp_sector_contribution_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/sector-contribution")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"


_GDP_HEADWIND_SERIES = ("FRGSHPUSM649NCIS", "DFEDTARL", "DFEDTARU", "T10Y2Y", "PCEPILFE")


def _gdp_headwinds_scenarios() -> dict:
    return {
        "FRGSHPUSM649NCIS": _overview_obs([("2026-06-01", "-3.07"), ("2026-05-01", "2.97")]),
        "DFEDTARL": _overview_obs([("2026-07-17", "5.25")]),
        "DFEDTARU": _overview_obs([("2026-07-17", "5.50")]),
        "T10Y2Y": _overview_obs([("2026-07-17", "0.39"), ("2026-07-16", "0.41")]),
        "PCEPILFE": _overview_obs([("2026-05-01", "2.8"), ("2026-04-01", "2.9")]),
    }


@responses.activate
def test_economy_gdp_growth_headwinds_missing_fred_key(client):
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/economy/gdp/growth-headwinds")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Missing FRED_API_KEY"


@responses.activate
def test_economy_gdp_growth_headwinds_success(client):
    captured: dict[str, list[str]] = {}

    def callback(request):
        qs = parse_qs(urlparse(request.url).query)
        sid = (qs.get("series_id") or [""])[0]
        captured.setdefault("series_id", []).append(sid)
        captured.setdefault("units", []).append((qs.get("units") or [""])[0])
        captured.setdefault("limit", []).append((qs.get("limit") or [""])[0])
        body = _gdp_headwinds_scenarios().get(sid)
        if body is None:
            return (404, {}, "")
        return (200, {}, json.dumps(body))

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
        resp = client.get("/api/economy/gdp/growth-headwinds")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(captured["series_id"]) == set(_GDP_HEADWIND_SERIES)
    assert captured["limit"] == ["2"] * len(_GDP_HEADWIND_SERIES)
    assert captured["units"].count("pch") == 1
    assert captured["units"].count("pc1") == 1

    risks = {row["key"]: row for row in data["risks"]}
    assert len(risks) == 4
    assert risks["supply_chain"]["value"] == -3.1
    assert risks["supply_chain"]["previous_value"] == 3.0
    assert risks["supply_chain"]["risk"] == "high"
    assert "declined 3.1%" in risks["supply_chain"]["body"]
    assert risks["interest_rates"]["target_lower"] == 5.25
    assert risks["interest_rates"]["target_upper"] == 5.5
    assert risks["interest_rates"]["risk"] == "high"
    assert risks["yield_curve"]["value"] == 0.39
    assert risks["yield_curve"]["risk"] == "medium"
    assert "Flat yield curve" in risks["yield_curve"]["body"]
    assert risks["inflation"]["value"] == 2.8
    assert risks["inflation"]["risk"] == "medium"
    assert "Fed's 2% target" in risks["inflation"]["body"]


@responses.activate
def test_economy_gdp_growth_headwinds_one_series_failed(client):
    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=_fred_callback(_gdp_headwinds_scenarios(), http_404_series="T10Y2Y"),
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/growth-headwinds")
    assert resp.status_code == 200
    risks = {row["key"]: row for row in resp.get_json()["risks"]}
    assert risks["yield_curve"]["value"] is None
    assert "error" in risks["yield_curve"]
    assert risks["supply_chain"]["value"] == -3.1


@responses.activate
def test_economy_gdp_growth_headwinds_network_failed(client):
    def callback(_request):
        raise requests.exceptions.ConnectionError("network down")

    responses.add_callback(
        responses.GET,
        re.compile(r"https://api\.stlouisfed\.org/fred/series/observations"),
        callback=callback,
        content_type="application/json",
    )
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/gdp/growth-headwinds")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "FRED API unavailable"
