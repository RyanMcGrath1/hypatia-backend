# Hypatia Backend — Frontend API Reference

Handoff doc for the Expo app: **current paths**, **breaking changes**, and **response shapes**.

---

## Base URL

```
{API_BASE}
```

Examples:

- iOS Simulator / local web: `http://127.0.0.1:5001`
- Physical device on LAN: `http://<your-machine-ip>:5001`

Default port is **5001** (see `PORT` in server `.env`). The server binds `0.0.0.0` so LAN clients can reach it.

**No API keys in the client.** All upstream keys are on the server.

**Optional header:** `X-Request-ID` — echoed on the response (also exposed via CORS).

---

## Breaking path changes

Update these calls in the mobile app:

| ❌ Stop using | ✅ Use instead |
|---------------|----------------|
| `GET /api/economy/overview` | `GET /api/economy/dashboard` |
| `GET /api/economy/sector` | `GET /api/economy/labor/sector` |

`/api/economy/overview` and `/api/economy/sector` return **404**.

---

## Shared observation window (YTD UTC)

Several labor and rates endpoints accept optional `observation_start` / `observation_end` (`YYYY-MM-DD`, inclusive).

**Default when both omitted:** year-to-date UTC — `Jan 1` of the current UTC year through today.

| You send | Window |
|----------|--------|
| (nothing) | YTD UTC |
| `observation_start` only | `observation_start` → today (UTC) |
| `observation_end` only | Jan 1 of that year → `observation_end` |
| both | exact inclusive range (`start` must be ≤ `end`) |

Invalid or inverted ranges return **400**.

---

## Economy routes — do not mix these up

| Path | What it is | FRED data |
|------|------------|-----------|
| `GET /api/economy/dashboard` | **Whole Economy tab** — all macro sections | GDPC1, PCE, UNRATE, FEDFUNDS, CPIAUCSL, CSUSHPISA |
| `GET /api/economy/labor/sector` | **Payroll-by-industry chart** | PAYEMS, USPBS, USEHS, … |

**Common mistake:** the Economy tab’s `labor` section is the **unemployment rate** (`UNRATE` inside `/api/economy/dashboard`). `labor/sector` is the **employment levels by industry** chart. They are not interchangeable.

```
/api/economy/dashboard              →  all sections (Economy tab), including UNRATE
/api/economy/labor/sector           →  payroll chart (sixteen series)
```

---

## `GET /api/economy/dashboard`

**Purpose:** Economy tab snapshot — every section in one response.

### Query

| Parameter | Required | Format | Notes |
|-----------|----------|--------|-------|
| `observation_end` | No | `YYYY-MM-DD` | Shared vintage for all sections |

### Response `200`

```json
{
  "as_of": "2026-05-18T17:30:00+00:00",
  "observation_end": "2025-11-01",
  "sections": {
    "gdp": {
      "label": "Real Gross Domestic Product",
      "series_id": "GDPC1",
      "unit": "billions of chained 2017 dollars",
      "observations": [
        { "date": "2026-01-01", "value": 23100.0 }
      ]
    },
    "inflation": {
      "label": "Consumer Price Index for All Urban Consumers: All Items",
      "series_id": "CPIAUCSL",
      "unit": "index",
      "observations": [],
      "momInflation": 0.33,
      "yoyInflation": 4.17,
      "acceleration": "decelerating"
    }
  }
}
```

### Section keys in `sections`

| Key | FRED series | Topic |
|-----|-------------|--------|
| `gdp` | GDPC1 | Real GDP |
| `consumer_spending` | PCE | Personal consumption |
| `labor` | UNRATE | Unemployment rate |
| `interest_rates` | FEDFUNDS | Fed funds rate |
| `inflation` | CPIAUCSL | CPI (includes `momInflation`, `yoyInflation`, `acceleration` on section + observations) |
| `housing` | CSUSHPISA | Case-Shiller home price index |

Observations are **newest first** within each section (compact overview window, not full YTD history).

### Errors

| Status | `error` |
|--------|---------|
| 400 | `Invalid observation_end` |
| 503 | `Missing FRED_API_KEY` |

### Example

```http
GET /api/economy/dashboard
GET /api/economy/dashboard?observation_end=2025-11-01
```

---

## `GET /api/economy/rates/fed-funds-target`

**Purpose:** FOMC fed funds **target range** widget on the rates page (not the effective `FEDFUNDS` rate).

Fetches FRED `DFEDTARL` (lower bound) and `DFEDTARU` (upper bound) via `series/observations`. Both series are daily and step on FOMC decision days.

### Query

Same [shared observation window](#shared-observation-window-ytd-utc) (default **YTD UTC**).

| Parameter | Required | Format |
|-----------|----------|--------|
| `observation_start` | No | `YYYY-MM-DD` |
| `observation_end` | No | `YYYY-MM-DD` |

### Response `200`

```json
{
  "as_of": "2026-05-18T17:30:00+00:00",
  "start_date": "2026-01-01",
  "end_date": "2026-05-18",
  "target_lower": 3.5,
  "target_upper": 3.75,
  "observation_date": "2026-05-01",
  "series": [
    {
      "id": "DFEDTARL",
      "name": "Federal Funds Target Range - Lower Limit",
      "observations": [
        { "date": "2026-05-01", "value": "3.50" }
      ]
    },
    {
      "id": "DFEDTARU",
      "name": "Federal Funds Target Range - Upper Limit",
      "observations": [
        { "date": "2026-05-01", "value": "3.75" }
      ]
    }
  ]
}
```

**Headline:** use `target_lower`, `target_upper`, and `observation_date` (e.g. display `3.50%–3.75%`).

**Chart:** use `series` (same envelope as `labor/sector`). Values are strings when present; `null` when FRED reported missing (`"."`).

Per-series `"error"` is included when that FRED fetch fails; headline fields are then `null`.

### Errors

| Status | `error` |
|--------|---------|
| 400 | invalid / inverted dates (message in `error`, hint in `hint`) |
| 503 | `Missing FRED_API_KEY` |
| 503 | `FRED API unavailable` (both series failed at network layer) |

### Example

```http
GET /api/economy/rates/fed-funds-target
GET /api/economy/rates/fed-funds-target?observation_start=2024-01-01&observation_end=2026-05-18
```

---

## `GET /api/economy/rates/key-metrics`

**Purpose:** KEY METRICS widget on the rates detail page — latest treasury yields and mortgage rate.

Fetches FRED `DGS10`, `MORTGAGE30US`, and `DGS2` via `series/observations` (`sort_order=desc`, `limit=1`).

### Response `200`

```json
{
  "as_of": "2026-05-18T17:30:00+00:00",
  "metrics": [
    {
      "series_id": "DGS10",
      "label": "10Y Treasury",
      "note": "Benchmark long rate",
      "value": 4.25,
      "observation_date": "2026-07-17"
    },
    {
      "series_id": "MORTGAGE30US",
      "label": "30Y Mortgage",
      "note": "Constrained affordability",
      "value": 6.81,
      "observation_date": "2026-07-10"
    },
    {
      "series_id": "DGS2",
      "label": "2Y Treasury",
      "note": "Policy-sensitive yield",
      "value": 4.72,
      "observation_date": "2026-07-17"
    }
  ]
}
```

Per-metric `"error"` is included when that FRED fetch fails; `value` and `observation_date` are then `null`.

### Errors

| Status | `error` |
|--------|---------|
| 503 | `Missing FRED_API_KEY` |
| 503 | `FRED API unavailable` (all series failed at network layer) |

### Example

```http
GET /api/economy/rates/key-metrics
```

---

## `GET /api/economy/labor/sector`

**Purpose:** Multi-series payroll chart — employment **levels** by industry (not UNRATE).

### Query

Same [shared observation window](#shared-observation-window-ytd-utc) (default **YTD UTC**).

| Parameter | Required | Format |
|-----------|----------|--------|
| `observation_start` | No | `YYYY-MM-DD` |
| `observation_end` | No | `YYYY-MM-DD` |

### Response `200`

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-05-18",
  "series": [
    {
      "id": "PAYEMS",
      "name": "Total Nonfarm Payrolls",
      "observations": [
        { "date": "2026-04-01", "value": "158123" },
        { "date": "2026-05-01", "value": null }
      ]
    }
  ]
}
```

**Use `series`** (ordered list). Lookup by FRED id: `series.find(s => s.id === "PAYEMS")`.

**Values:** string when present; `null` when FRED reported missing (`"."`). Do not treat `null` as zero.

**Per-series failure:** still `200`; failed id has `"error": "..."` and `"observations": []`.

### Series order in `series` (canonical)

| `id` | `name` |
|------|--------|
| `PAYEMS` | Total Nonfarm Payrolls |
| `USPRIV` | Total Private |
| `USGOOD` | Goods-Producing |
| `SRVPRD` | Service-Providing |
| `USPBS` | Professional & Business Services |
| `USEHS` | Education & Health Services |
| `USLAH` | Leisure & Hospitality |
| `USTRADE` | Retail Trade |
| `MANEMP` | Manufacturing |
| `USFIRE` | Financial Activities |
| `USCONS` | Construction |
| `USINFO` | Information |
| `USGOVT` | Government |
| `CES4300000001` | Transportation & Warehousing |
| `USWTRADE` | Wholesale Trade |
| `USMINE` | Mining & Logging |

### Errors

| Status | `error` |
|--------|---------|
| 400 | invalid date range |
| 503 | `Missing FRED_API_KEY` |
| 503 | `FRED API unavailable` (all series failed at network layer) |

### Examples

```http
GET /api/economy/labor/sector
GET /api/economy/labor/sector?observation_start=2024-06-01&observation_end=2025-12-31
```

---

## `GET /api/economy/inflation/pce-vs-target`

**Purpose:** Headline and core PCE year-over-year inflation vs the Fed’s 2% target (inflation detail “PCE vs target” widget).

Fetches FRED `PCEPI` and `PCEPILFE` with `units=pc1` (percent change from year ago). The target is returned as a constant (`2.0`); it is not a FRED series.

### Response `200`

```json
{
  "as_of": "2026-05-18T17:30:00+00:00",
  "target": 2.0,
  "headline": {
    "series_id": "PCEPI",
    "label": "PCE Headline",
    "value": 2.4,
    "observation_date": "2026-05-01"
  },
  "core": {
    "series_id": "PCEPILFE",
    "label": "Core PCE",
    "value": 2.8,
    "observation_date": "2026-05-01"
  }
}
```

Per-metric `"error"` is included when that FRED fetch fails; `value` and `observation_date` are then `null`.

### Errors

| Status | `error` |
|--------|---------|
| 503 | `Missing FRED_API_KEY` |
| 503 | `FRED API unavailable` (both series failed at network layer) |

### Example

```http
GET /api/economy/inflation/pce-vs-target
```

---

## `GET /api/economy/inflation/cpi-components`

**Purpose:** Headline CPI and component year-over-year inflation for the inflation detail “CPI components” widget.

Fetches FRED `CPIAUCSL` plus five BLS CPI component indexes with `units=pc1` (percent change from year ago). All series are seasonally adjusted. Shelter is nested inside core services; the response includes `includes_in: ["core_services"]` on the shelter entry so the UI can show that overlap.

| Component key | FRED series | Label |
|---------------|-------------|-------|
| *(headline)* | `CPIAUCSL` | Headline CPI |
| `shelter` | `CUSR0000SAH1` | Shelter |
| `food` | `CPIUFDSL` | Food |
| `energy` | `CPIENGSL` | Energy |
| `core_goods` | `CUSR0000SACL1E` | Core Goods |
| `core_services` | `CUSR0000SASLE` | Core Services |

### Response `200`

```json
{
  "as_of": "2026-07-18T02:00:00+00:00",
  "observation_date": "2026-06-01",
  "headline": {
    "series_id": "CPIAUCSL",
    "label": "Headline CPI",
    "value": 3.5,
    "observation_date": "2026-06-01",
    "previous_value": 3.2,
    "previous_observation_date": "2026-05-01",
    "delta": 0.3
  },
  "components": [
    {
      "key": "shelter",
      "series_id": "CUSR0000SAH1",
      "label": "Shelter",
      "value": 3.3,
      "observation_date": "2026-06-01",
      "previous_value": 3.1,
      "previous_observation_date": "2026-05-01",
      "delta": 0.2,
      "includes_in": ["core_services"]
    },
    {
      "key": "food",
      "series_id": "CPIUFDSL",
      "label": "Food",
      "value": 3.0,
      "observation_date": "2026-06-01"
    },
    {
      "key": "energy",
      "series_id": "CPIENGSL",
      "label": "Energy",
      "value": 15.7,
      "observation_date": "2026-06-01"
    },
    {
      "key": "core_goods",
      "series_id": "CUSR0000SACL1E",
      "label": "Core Goods",
      "value": 0.8,
      "observation_date": "2026-06-01"
    },
    {
      "key": "core_services",
      "series_id": "CUSR0000SASLE",
      "label": "Core Services",
      "value": 3.2,
      "observation_date": "2026-06-01"
    }
  ]
}
```

Per-metric `"error"` is included when that FRED fetch fails; numeric fields are then `null`. Each metric includes latest YoY % (`value`), prior month YoY % (`previous_value`), and the change in the YoY rate in percentage points (`delta`).

### Errors

| Status | `error` |
|--------|---------|
| 503 | `Missing FRED_API_KEY` |
| 503 | `FRED API unavailable` (all series failed at network layer) |

### Example

```http
GET /api/economy/inflation/cpi-components
```

---

## `GET /api/economy/labor/payems/delta`

**Purpose:** PAYEMS month-over-month change (`units=chg`).

Optional: `observation_start`, `observation_end`, `limit`, `sort_order`.

```http
GET /api/economy/labor/payems/delta?limit=72&sort_order=desc
```

---

## FEC (candidate search)

### `GET /api/fec/candidates`

| Parameter | Required | Notes |
|-----------|----------|-------|
| `q` or `name` | **Yes** | `name` is alias for `q` |
| `page` | No | |
| `per_page` | No | server default **5** if omitted |
| `typeahead` | No | `1` / `true` / `yes` → shorter timeout |

```http
GET /api/fec/candidates?q=smith
```

**503** if `Missing OPENFEC_API_KEY`.

---

## News (GNews)

### `GET /api/news/top-headlines`

Pagination: **`page`** (1-based), **`max`** (page size; default **20**, cap **50**).

Optional **`offset`** (0-based): must be a multiple of `max` if used without `page`.

Response includes `items` / `articles` (same array), `hasMore`, `nextPage`, `nextOffset`, `page`, `max`, `total`.

```http
GET /api/news/top-headlines?lang=en
GET /api/news/top-headlines?lang=en&max=10&page=2
```

**503** if `Missing GNEWS_API_KEY`.

---

## Health

| Path | Response |
|------|----------|
| `GET /health` | `200` `{"message": "hello"}` — liveness / load balancers |

---

## Global errors

| Status | When |
|--------|------|
| 404 | Unknown path → `{"error": "Not Found"}` |
| 500 | Unhandled server error → `{"error": "Internal Server Error"}` |
| 503 | Missing env API key → `{"error": "Missing <KEY_NAME>", "hint": "..."}` |

---

## TypeScript (economy)

```ts
export type SectorObservation = { date: string; value: string | null };

export type DashboardObservation = {
  date: string;
  value?: number | string;
  momInflation?: number | null;
  yoyInflation?: number | null;
  acceleration?: string | null;
};

export type EconomySection = {
  label?: string;
  series_id?: string;
  unit?: string;
  observations?: DashboardObservation[];
  momInflation?: number | null;
  yoyInflation?: number | null;
  acceleration?: string | null;
  error?: string;
  hint?: string;
};

export type EconomyDashboardResponse = {
  as_of: string;
  observation_end?: string;
  sections: Record<string, EconomySection>;
};

export type EmploymentSeries = {
  id: string;
  name: string;
  observations: SectorObservation[];
  error?: string;
};

export type LaborSectorResponse = {
  start_date: string;
  end_date: string;
  series: EmploymentSeries[];
};
```

---

## Expo find-and-replace

```text
"/api/economy/overview"     →  "/api/economy/dashboard"
"/api/economy/sector"       →  "/api/economy/labor/sector"
"/api/economy/fred/series/PAYEMS/delta" → "/api/economy/labor/payems/delta"
```

---

## Full route index

| Method | Path |
|--------|------|
| GET | `/health` |
| GET | `/api/economy/dashboard` |
| GET | `/api/economy/cpi` |
| GET | `/api/economy/gdp/growth-rate` |
| GET | `/api/economy/gdp/sector-contribution` |
| GET | `/api/economy/gdp/growth-headwinds` |
| GET | `/api/economy/labor/sector` |
| GET | `/api/economy/labor/age-metrics` |
| GET | `/api/economy/labor/earnings-inflation` |
| GET | `/api/economy/rates/fed-funds-target` |
| GET | `/api/economy/rates/key-metrics` |
| GET | `/api/economy/inflation/pce-vs-target` |
| GET | `/api/economy/inflation/cpi-components` |
| GET | `/api/economy/labor/payems/delta` |
| GET | `/api/fec/candidates` |
| GET | `/api/news/top-headlines` |
