"""Tests for economy FRED routes (mocked HTTP)."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
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
        resp = client.get("/api/economy/overview")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["error"] == "Missing FRED_API_KEY"
    assert "hint" in data


def test_economy_dashboard_path_returns_404(client):
    resp = client.get("/api/economy/dashboard")
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
@patch("economy._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
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
@patch("economy._sector_dashboard_clock_today", return_value=date(2026, 6, 1))
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

    inf = sections["inflation"]
    assert inf["momInflation"] == inf["observations"][0]["momInflation"]
    assert inf["yoyInflation"] is None
    assert inf["observations"][0]["momInflation"] == pytest.approx(0.62)
    assert inf["observations"][0]["yoyInflation"] is None
    assert inf["observations"][0]["acceleration"] == "decelerating"


def test_economy_overview_invalid_observation_end(client):
    with patch.dict(os.environ, {"FRED_API_KEY": "k"}):
        resp = client.get("/api/economy/overview?observation_end=not-a-date")
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
        resp = client.get("/api/economy/overview?observation_end=2025-11-01")
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
        resp = client.get("/api/economy/overview")
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
        resp = client.get("/api/economy/overview")
    assert resp.status_code == 200
    sections = resp.get_json()["sections"]
    assert "error" in sections["gdp"]
    assert sections["labor"]["series_id"] == "UNRATE"


_EMPLOYMENT_SECTOR_IDS = (
    "PAYEMS",
    "USPBS",
    "USEHS",
    "USLAH",
    "USTRADE",
    "MANEMP",
    "USFIRE",
    "USCONS",
    "USINFO",
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
        patch("economy._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["start_date"] == "2026-01-01"
    assert data["end_date"] == "2026-05-18"
    assert set(data["sectors"].keys()) == set(_EMPLOYMENT_SECTOR_IDS)
    payems = data["sectors"]["PAYEMS"]
    assert payems["name"] == "Total Nonfarm Payrolls"
    assert "error" not in payems
    assert payems["observations"][0] == {"date": "2026-04-01", "value": "100"}
    series_ids = [s["id"] for s in data["series"]]
    assert series_ids == list(_EMPLOYMENT_SECTOR_IDS)
    assert data["series"][0]["points"][0] == ["2026-04-01", "100"]


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
        patch("economy._sector_dashboard_clock_today", return_value=fixed_today),
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
            "/api/economy/labor/sector"
            "?observation_start=2024-06-01&observation_end=2025-12-31"
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
        patch("economy._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    sectors = resp.get_json()["sectors"]
    assert sectors["MANEMP"]["error"] == "FRED returned HTTP 404"
    assert sectors["MANEMP"]["observations"] == []
    assert "error" not in sectors["PAYEMS"]


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
        patch("economy._sector_dashboard_clock_today", return_value=fixed_today),
    ):
        resp = client.get("/api/economy/labor/sector")
    assert resp.status_code == 200
    payems = resp.get_json()["sectors"]["PAYEMS"]["observations"]
    assert payems[0] == {"date": "2026-04-01", "value": None}
    assert payems[1] == {"date": "2026-05-01", "value": "101"}


def test_economy_labor_sector_returns_503_when_all_network_failed(client):
    fixed_today = date(2026, 5, 18)

    def boom(*_args, **_kwargs):
        return {"observations": [], "error": "FRED request failed: boom"}

    with (
        patch.dict(os.environ, {"FRED_API_KEY": "k"}),
        patch("economy._sector_dashboard_clock_today", return_value=fixed_today),
        patch("economy.fetch_fred_series", side_effect=boom),
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
