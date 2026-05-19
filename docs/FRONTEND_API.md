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

## Economy routes — do not mix these up

Three different economy resources. The path names are similar; the data is not.

| Path | What it is | FRED data |
|------|------------|-----------|
| `GET /api/economy/dashboard` | **Whole Economy tab** — all macro sections | GDPC1, PCE, UNRATE, FEDFUNDS, CPIAUCSL, CSUSHPISA |
| `GET /api/economy/{sector}/dashboard` | **One section** drill-down | Same series as that section (e.g. `labor` → **UNRATE**) |
| `GET /api/economy/labor/sector` | **Payroll-by-industry chart** (9 lines) | PAYEMS, USPBS, USEHS, … |

**Common mistake:** `labor/dashboard` is the **unemployment rate** screen. `labor/sector` is the **employment levels by industry** chart. They are not interchangeable.

```
/api/economy/dashboard              →  all sections (Economy tab)
/api/economy/labor/dashboard        →  unemployment rate only (UNRATE)
/api/economy/labor/sector           →  payroll chart (9 series)
/api/economy/gdp/dashboard          →  GDP section only
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

## `GET /api/economy/{sector}/dashboard`

**Purpose:** Single Economy section with a configurable date window.

### Path `{sector}`

| URL segment | Resolves to |
|-------------|-------------|
| `gdp` | `gdp` |
| `consumer_spending` | `consumer_spending` |
| `consumer` | `consumer_spending` (alias) |
| `labor` | `labor` |
| `inflation` | `inflation` |
| `housing` | `housing` |
| `interest_rates` | `interest_rates` |
| `rates` | `interest_rates` (alias) |

### Query

| Parameter | Required | Format | Notes |
|-----------|----------|--------|-------|
| `observation_start` | No | `YYYY-MM-DD` | Inclusive start |
| `observation_end` | No | `YYYY-MM-DD` | Inclusive end |

**Default when both omitted:** year-to-date UTC — `Jan 1` of the current UTC year through today.

| You send | Window |
|----------|--------|
| (nothing) | YTD UTC |
| `observation_start` only | `observation_start` → today (UTC) |
| `observation_end` only | Jan 1 of that year → `observation_end` |
| both | exact inclusive range (`start` must be ≤ `end`) |

### Response `200`

Same section object shape as `/api/economy/dashboard`, wrapped with window metadata:

```json
{
  "as_of": "2026-05-18T17:30:00+00:00",
  "observation_start": "2026-01-01",
  "observation_end": "2026-05-18",
  "sections": {
    "labor": {
      "label": "Unemployment Rate",
      "series_id": "UNRATE",
      "unit": "percent",
      "observations": [
        { "date": "2026-03-01", "value": 4.0 }
      ]
    }
  }
}
```

### Errors

| Status | `error` |
|--------|---------|
| 404 | `Unknown economy sector` |
| 400 | invalid / inverted dates (message in `error`, hint in `hint`) |
| 503 | `Missing FRED_API_KEY` |

### Examples

```http
GET /api/economy/labor/dashboard
GET /api/economy/gdp/dashboard?observation_start=2025-01-01&observation_end=2025-06-30
GET /api/economy/rates/dashboard
```

---

## `GET /api/economy/labor/sector`

**Purpose:** Multi-series payroll chart — employment **levels** by industry (not UNRATE).

### Query

Same window rules as `{sector}/dashboard` (default **YTD UTC**).

| Parameter | Required | Format |
|-----------|----------|--------|
| `observation_start` | No | `YYYY-MM-DD` |
| `observation_end` | No | `YYYY-MM-DD` |

### Response `200`

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-05-18",
  "sectors": {
    "PAYEMS": {
      "name": "Total Nonfarm Payrolls",
      "observations": [
        { "date": "2026-04-01", "value": "158123" },
        { "date": "2026-05-01", "value": null }
      ]
    }
  },
  "series": [
    {
      "id": "PAYEMS",
      "name": "Total Nonfarm Payrolls",
      "points": [["2026-04-01", "158123"], ["2026-05-01", null]]
    }
  ]
}
```

**Use `series` for charts** (stable order). Use `sectors` for lookup by FRED id.

**Values:** string when present; `null` when FRED reported missing (`"."`). Do not treat `null` as zero.

**Per-series failure:** still `200`; failed id has `"error": "..."` and `"observations": []`.

### Series order in `series` (canonical)

| `id` | `name` |
|------|--------|
| `PAYEMS` | Total Nonfarm Payrolls |
| `USPBS` | Professional & Business Services |
| `USEHS` | Education & Health Services |
| `USLAH` | Leisure & Hospitality |
| `USTRADE` | Retail Trade |
| `MANEMP` | Manufacturing |
| `USFIRE` | Financial Activities |
| `USCONS` | Construction |
| `USINFO` | Information Sector |

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

## `GET /api/economy/fred/observations`

**Purpose:** Thin FRED proxy for custom series.

| Parameter | Required | Notes |
|-----------|----------|-------|
| `series_id` | **Yes** | |
| `observation_start` | No | |
| `observation_end` | No | |
| `limit` | No | default `60`, max `10000` |
| `sort_order` | No | e.g. `desc` for newest first |

Returns **raw FRED JSON** (not the Hypatia `sections` envelope).

```http
GET /api/economy/fred/observations?series_id=PAYEMS&limit=72&sort_order=desc
```

---

## `GET /api/economy/fred/series/PAYEMS/delta`

**Purpose:** PAYEMS month-over-month change (`units=chg`).

Optional: `observation_start`, `observation_end`, `limit`, `sort_order`.

```http
GET /api/economy/fred/series/PAYEMS/delta?limit=72&sort_order=desc
```

---

## Civic

### `GET /api/civic/divisions-by-address`

| Parameter | Required |
|-----------|----------|
| `address` | **Yes** |

```http
GET /api/civic/divisions-by-address?address=1600+Pennsylvania+Ave+NW+Washington+DC
```

**503** if `Missing GOOGLE_CIVIC_API_KEY`.

### `GET /api/civic/representatives`

**410 Gone** — API removed by Google in 2025. Use divisions-by-address.

---

## FEC (candidate search)

Both paths are identical:

- `GET /api/fec/candidates`
- `GET /api/fec/v1/names/candidates`

| Parameter | Required | Notes |
|-----------|----------|-------|
| `q` or `name` | **Yes** | `name` is alias for `q` |
| `page` | No | |
| `per_page` | No | server default **5** if omitted |
| `typeahead` | No | `1` / `true` / `yes` → shorter timeout |

```http
GET /api/fec/candidates?q=smith
GET /api/fec/v1/names/candidates?name=jane%20doe&typeahead=1
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

### `GET /api/news/search`

| Parameter | Required |
|-----------|----------|
| `q` | **Yes** |

Plus optional GNews params (`lang`, `max`, …).

```http
GET /api/news/search?q=climate&lang=en
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

export type SectorDashboardResponse = {
  as_of: string;
  observation_start: string;
  observation_end: string;
  sections: Record<string, EconomySection>;
};

export type EmploymentSector = {
  name: string;
  observations: SectorObservation[];
  error?: string;
};

export type EmploymentSeries = {
  id: string;
  name: string;
  points: [string, string | null][];
  error?: string;
};

export type LaborSectorResponse = {
  start_date: string;
  end_date: string;
  sectors: Record<string, EmploymentSector>;
  series: EmploymentSeries[];
};
```

---

## Expo find-and-replace

```text
"/api/economy/overview"     →  "/api/economy/dashboard"
"/api/economy/sector"       →  "/api/economy/labor/sector"
```

Verify anything that called **`/api/economy/labor/dashboard`** still should — that path is unchanged and still means UNRATE, not the payroll chart.

---

## Full route index

| Method | Path |
|--------|------|
| GET | `/health` |
| GET | `/api/civic/divisions-by-address` |
| GET | `/api/civic/representatives` (410) |
| GET | `/api/economy/dashboard` |
| GET | `/api/economy/{sector}/dashboard` |
| GET | `/api/economy/labor/sector` |
| GET | `/api/economy/fred/observations` |
| GET | `/api/economy/fred/series/PAYEMS/delta` |
| GET | `/api/fec/candidates` |
| GET | `/api/fec/v1/names/candidates` |
| GET | `/api/news/top-headlines` |
| GET | `/api/news/search` |
