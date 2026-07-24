# hypatia-backend

Flask API for Hypatia (FRED-backed economy dashboard, OpenFEC candidate name search proxy, GNews proxy for top headlines, and health checks).

## Project layout

| Path | Role |
|------|------|
| [app.py](app.py) | Dev entrypoint: `create_app()` + `python app.py` (re-exports `app` for `flask --app app`). |
| [wsgi.py](wsgi.py) | WSGI entry: `application = create_app()` for Gunicorn (`wsgi:application` or alias `wsgi:app`). |
| [hypatia/](hypatia/__init__.py) | Application factory ([`create_app`](hypatia/__init__.py)). Cross-cutting helpers under [utils/](hypatia/utils/): [settings](hypatia/utils/settings.py) (`development` / `production` / `testing`), [CORS](hypatia/utils/cors.py), [logging](hypatia/utils/logging_config.py), [HTTP helpers](hypatia/utils/http.py), [JSON error handlers](hypatia/utils/error_handlers.py). Application vs account-audit vs security logging: [docs/LOGGING_AND_AUDIT.md](docs/LOGGING_AND_AUDIT.md). |
| [hypatia/routes/](hypatia/routes/__init__.py) | Flask blueprints grouped like Expo `hooks/api/` (see [docs/API_STRUCTURE.md](docs/API_STRUCTURE.md)). |
| [hypatia/services/](hypatia/services/) | Domain logic and upstream clients (FRED economy, GNews). |
| [economy.py](economy.py), [news.py](news.py) | Re-export shims for tests/legacy imports (implementation in `hypatia/services/`). |
| [pyproject.toml](pyproject.toml) | Project metadata (`requires-python`), Ruff, pytest. |
| [Dockerfile](Dockerfile) | Minimal production-shaped image (Gunicorn + `HYPATIA_ENV=production`). |

Tests use `create_app("testing")` via [tests/conftest.py](tests/conftest.py); CI runs Ruff and pytest on Python 3.10 and 3.12 ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Requirements

- Python 3.10 or newer

## Setup

```bash
python -m venv .venv
```

Activate the virtual environment (Windows PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Optional dev / test tools:

```bash
pip install -r requirements-dev.txt
```

Copy [.env.example](.env.example) to `.env` and set `FRED_API_KEY` (economy routes), `GNEWS_API_KEY` (news routes), and `OPENFEC_API_KEY` (FEC routes) as needed. Never commit `.env`.

**API keys**

- `FRED_API_KEY` — [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html) key from [your FRED account](https://fredaccount.stlouisfed.org/apikeys); required for economy routes (`GET /api/economy/dashboard`, `GET /api/economy/labor/sector`, `GET /api/economy/fred/series/PAYEMS/delta`, and related labor/rates/inflation/GDP widgets)
- `GNEWS_API_KEY` — [GNews](https://gnews.io/) API key; required for `GET /api/news/top-headlines`
- `OPENFEC_API_KEY` — [OpenFEC](https://api.open.fec.gov/developers/) API key; required for `GET /api/fec/candidates`

Optional environment variables:

- `HYPATIA_ENV` or `FLASK_ENV` — `development` (default), `production`, or `testing` (pytest uses `testing` via the app factory; not usually set by hand)
- `SECRET_KEY` — set in production for signed cookies and similar; a dev-only default is used if unset (see [hypatia/utils/settings.py](hypatia/utils/settings.py))
- `EXPO_CORS_EXTRA_ORIGINS` — comma-separated extra allowed origins (e.g. tunnel URLs like ngrok)
- `CORS_ALLOW_ALL_ORIGINS` — set to `1`, `true`, or `yes` to allow **any** `Origin` (local debugging only; never in production)
- `PORT` — listen port when using `python app.py` (default `5001`; macOS often reserves `5000` for AirPlay Receiver)
- `FLASK_DEBUG` or `DEBUG` — set to `1`, `true`, `yes`, or `on` so **`DevelopmentConfig`** sets `DEBUG` (used by `python app.py` and `app.config`; default is off)
- `LOG_LEVEL` — Python logging level (default `INFO`; use `DEBUG` for more detail)
- `LOG_FORMAT` — `text` (default) or `json` (one JSON object per line for log aggregators; **no ANSI colors**)
- `LOG_COLOR` — `auto` (default): color **text** logs when stderr is a TTY; `always` / `never` to force on or off (use `never` when piping logs to a file)
- `LOG_QUIET_HEALTH` — when truthy (default `1`), skip access-style log lines for `/health` at INFO; set `LOG_VERBOSE_HEALTH` to log them
- `LOG_VERBOSE_HEALTH` — if truthy, log health routes even when quiet health is on (overrides the skip). Truthy values: `1`, `true`, `yes`, `on`

### Logging

Hypatia’s **text** logs use colors by default on interactive terminals (level, timestamp, logger name, request id). JSON logs stay plain for parsers. Control with **`LOG_COLOR`** (`auto` | `always` | `never`).

Each request gets a **`X-Request-ID`** (from the incoming `X-Request-ID` header or generated). The same value is returned on the response; CORS **exposes** this header for browser clients. Access logs include method, path, status, and duration (ms). Outbound calls to **GNews**, **OpenFEC**, and **FRED** log service name, endpoint label, status, and duration—**never** full URLs, query strings, or API keys. FRED failures inside the economy dashboard builders still log **warnings** with `section_key` / `series_id` only.

Flask’s **Werkzeug** dev-server lines (e.g. `127.0.0.1 - - [date] "GET /..."`) keep their default styling; Hypatia’s application log lines are what `LOG_LEVEL` / `LOG_FORMAT` control.

### CORS (Expo on your PC and on a phone)

The API listens on `0.0.0.0`, so on your phone use your computer’s **LAN IP** and port (e.g. `http://192.168.1.71:5001`). CORS allows typical Expo/Metro dev origins: `localhost` / `127.0.0.1` on any port, and `http://<private-LAN-ip>:<port>` (so when the phone loads the bundle from `http://192.168.x.x:8081`, browser preflights still succeed). For tunnels or odd origins, add them to `EXPO_CORS_EXTRA_ORIGINS`. If something still blocks requests during local dev only, set `CORS_ALLOW_ALL_ORIGINS=1` in `.env`.

## Run locally

Development uses **`HYPATIA_ENV` / `FLASK_ENV`** default `development`. The server binds `0.0.0.0` so LAN devices can reach it. Enable the debugger with `FLASK_DEBUG=1` (PowerShell: `$env:FLASK_DEBUG='1'; python app.py`); that matches `app.config["DEBUG"]` used by `app.run(...)`.

```bash
python app.py
```

With no `PORT` in `.env`, the server listens on **5001** (see optional env vars above). Use `source .venv/bin/activate` before `python app.py` if `python` is not on your PATH.

Run tests and lint (install [requirements-dev.txt](requirements-dev.txt) first):

```bash
pytest
ruff check .
ruff format --check .
```

Pytest uses colors when the terminal supports them; set [`FORCE_COLOR=1`](https://docs.pytest.org/en/stable/how-to/output.html) if you want colors in environments without a TTY (some CI logs).

Or with the Flask CLI:

```bash
flask --app app run --host 0.0.0.0 --port 5001
```

## Production (WSGI)

Use [wsgi.py](wsgi.py) with Gunicorn (set `HYPATIA_ENV=production` or `FLASK_ENV=production` and a strong `SECRET_KEY`):

```bash
gunicorn -w 2 -b 0.0.0.0:5001 wsgi:application
```

(`wsgi:app` is an alias of the same object.) A minimal container build is in [Dockerfile](Dockerfile); inject API keys and `SECRET_KEY` at runtime, not into the image.

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | JSON liveness check (load balancers) |
| GET | `/api/economy/cpi` | Last 5 months of FRED ``CPIAUCSL`` (Consumer Price Index), newest first; JSON has `as_of`, `series_id`, `label`, `unit`, `observations` |
| GET | `/api/economy/inflation/pce-vs-target` | Headline ``PCEPI`` and core ``PCEPILFE`` YoY (``units=pc1``) vs Fed 2% target; JSON has `as_of`, `target`, `headline`, `core` |
| GET | `/api/economy/inflation/cpi-components` | Headline ``CPIAUCSL`` and CPI component YoY (shelter, food, energy, core goods, core services); JSON has `as_of`, `observation_date`, `headline`, `components` |
| GET | `/api/economy/dashboard` | Economy tab snapshot: recent FRED observations per section; JSON has `as_of` and `sections` (see [Economy dashboard](#economy-dashboard-apieconomydashboard)) |
| GET | `/api/economy/gdp/growth-rate` | Real GDP QoQ growth for the GDP detail growth widget |
| GET | `/api/economy/gdp/sector-contribution` | Real value-added share of GDP by industry |
| GET | `/api/economy/gdp/growth-headwinds` | Macro headwinds for the GDP detail risks panel |
| GET | `/api/economy/labor/sector` | Employment levels across sixteen FRED payroll series; JSON has `start_date`, `end_date`, and `series` (see [Labor employment by sector](#labor-employment-by-sector-apieconomylaborsector)). **Default window:** year-to-date in UTC (Jan 1 through today). |
| GET | `/api/economy/labor/earnings-inflation` | `CES0500000003` (average hourly earnings) and `CPIAUCSL` (CPI inflation); same JSON shape as `labor/sector` (see [Labor earnings and CPI](#labor-earnings-and-cpi-apieconomylaborearnings-inflation)) |
| GET | `/api/economy/rates/fed-funds-target` | FOMC fed funds target range via FRED ``DFEDTARL`` and ``DFEDTARU``; JSON has `as_of`, `target_lower`, `target_upper`, `observation_date`, and `series` (see [Fed funds target range](#fed-funds-target-range-apieconomyratesfed-funds-target)) |
| GET | `/api/economy/rates/key-metrics` | Latest ``DGS10``, ``MORTGAGE30US``, and ``DGS2`` for the rates detail KEY METRICS widget; JSON has `as_of` and `metrics` (see [Rates key metrics](#rates-key-metrics-apieconomyrateskey-metrics)) |
| GET | `/api/economy/labor/age-metrics` | Unemployment, labor force participation, and employment-population ratio by age cohort (12 FRED `LNS*` series); see [Labor age metrics](#labor-age-metrics-apieconomylaborage-metrics) |
| GET | `/api/economy/fred/series/PAYEMS/delta` | PAYEMS-only monthly deltas via FRED observations (`units=chg`); optional `observation_start`, `observation_end`, `sort_order`, `limit` |
| GET | `/api/fec/candidates?...` | Proxies [OpenFEC `names/candidates`](https://api.open.fec.gov/developers/#/names/get_v1_names_candidates); `api_key` from env only |
| GET | `/api/news/top-headlines` | [GNews top headlines](https://docs.gnews.io/endpoints/top-headlines-endpoint) with **page/max pagination** and a stable JSON envelope; see [News routes](#news-routes) |

Economy routes that need FRED return **503** with `Missing FRED_API_KEY` when `FRED_API_KEY` is unset. News routes return **503** with `Missing GNEWS_API_KEY` when `GNEWS_API_KEY` is unset. OpenFEC routes return **503** with `Missing OPENFEC_API_KEY` when `OPENFEC_API_KEY` is unset. **Fix:** put keys in `.env` at the **repository root** (same directory as `app.py`), then **fully stop and restart** the Flask process (debug mode’s reloader still needs a restart after you first create `.env`).

Unknown paths return **404** with JSON `{"error": "Not Found"}`. Unhandled server errors return **500** with JSON `{"error": "Internal Server Error"}`.

### Recent CPI (`/api/economy/cpi`)

Returns the **5 most recent** monthly observations for FRED series **`CPIAUCSL`** (Consumer Price Index for All Urban Consumers: All Items), newest first.

Response (HTTP 200):

- `as_of` — ISO-8601 UTC timestamp when the snapshot was built
- `series_id` — always `CPIAUCSL`
- `label` / `unit` — display metadata (`index`)
- `observations` — up to 5 `{date, value}` rows (`value` is numeric when FRED returns a number; `"."` for missing)

Missing `FRED_API_KEY` → **503**. Upstream FRED errors are forwarded (e.g. **429**).

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/cpi"
```

### Economy dashboard (`/api/economy/dashboard`)

Returns **HTTP 200** with:

- `as_of`: ISO-8601 UTC timestamp when the snapshot was built.
- `sections`: object keyed by section; each value holds recent FRED observations for that overview series (newest first within each section).

Optional query: **`observation_end`** (`YYYY-MM-DD`) — forwarded to FRED so all sections share the same vintage window.

If `FRED_API_KEY` is missing, the route returns **503** with `Missing FRED_API_KEY`. The legacy path **`GET /api/economy/overview`** is not registered (returns **404**).

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/dashboard"
```

### PAYEMS monthly deltas (`/api/economy/fred/series/PAYEMS/delta`)

Returns PAYEMS month-over-month deltas directly from FRED (`units=chg`) so clients do not need to subtract levels manually. The server still injects `api_key` and `file_type=json`. Optional query params include `observation_start`, `limit`, and `sort_order`.

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/fred/series/PAYEMS/delta?limit=72&sort_order=desc"
```

### Labor employment by sector (`/api/economy/labor/sector`)

Returns employment **levels** (payroll-by-industry chart) for a fixed set of FRED payroll series, fetched in parallel. This is not the Economy tab’s unemployment-rate overview series (`UNRATE` in `GET /api/economy/dashboard`).

**Default window:** year-to-date in UTC (`Jan 1` through `today`). Optional **`observation_start`** / **`observation_end`** (`YYYY-MM-DD`, inclusive) override; invalid or inverted ranges return **400**.

Series (id → human name, response order):

- `PAYEMS` — Total Nonfarm Payrolls
- `USPRIV` — Total Private
- `USGOOD` — Goods-Producing
- `SRVPRD` — Service-Providing
- `USPBS` — Professional & Business Services
- `USEHS` — Education & Health Services
- `USLAH` — Leisure & Hospitality
- `USTRADE` — Retail Trade
- `MANEMP` — Manufacturing
- `USFIRE` — Financial Activities
- `USCONS` — Construction
- `USINFO` — Information
- `USGOVT` — Government
- `CES4300000001` — Transportation & Warehousing
- `USWTRADE` — Wholesale Trade
- `USMINE` — Mining & Logging

Response (HTTP 200) shape:

- `start_date` / `end_date` — inclusive FRED window (echoed from query params or YTD default), forwarded as `observation_start` / `observation_end`.
- `series` — ordered list of `{"id", "name", "observations": [{"date", "value"}]}`. FRED's `"."` is converted to `null`; everything else stays as the raw FRED string. On per-series failure the entry also includes `"error": "<message>"` and `"observations": []`.

`FRED_API_KEY` missing → **503** `Missing FRED_API_KEY` (consistent with the other economy routes). When **every** series fails at the network layer (timeout / connection error), the route returns **503** `FRED API unavailable`; otherwise individual failures are surfaced in-band per sector.

Example (port **5001**):

```bash
curl -sS "http://127.0.0.1:5001/api/economy/labor/sector"
```

### Labor earnings and CPI (`/api/economy/labor/earnings-inflation`)

Returns two FRED series in parallel (same response envelope as `labor/sector`):

- `CES0500000003` — Average Hourly Earnings
- `CPIAUCSL` — CPI Inflation

**Default window:** YTD UTC; optional `observation_start` / `observation_end` (`YYYY-MM-DD`).

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/labor/earnings-inflation"
```

### Fed funds target range (`/api/economy/rates/fed-funds-target`)

Returns the FOMC **target range** (not the effective rate) via two daily FRED series fetched in parallel:

- `DFEDTARL` — Federal Funds Target Range - Lower Limit
- `DFEDTARU` — Federal Funds Target Range - Upper Limit

**Default window:** YTD UTC; optional `observation_start` / `observation_end` (`YYYY-MM-DD`).

Response (HTTP 200):

- `as_of` — ISO-8601 UTC timestamp when the snapshot was built
- `start_date` / `end_date` — inclusive FRED window (echoed from query params or YTD default)
- `target_lower` / `target_upper` — latest numeric bounds in the window (`null` when either series failed)
- `observation_date` — date of those latest bounds
- `series` — ordered list of `{"id", "name", "observations": [{"date", "value"}]}` (`value` is string or `null`; per-series `"error"` on partial failure)

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/rates/fed-funds-target"
```

### Rates key metrics (`/api/economy/rates/key-metrics`)

Returns the latest values for three rates shown in the interest-rates detail **KEY METRICS** widget:

- `DGS10` — 10Y Treasury
- `MORTGAGE30US` — 30Y Mortgage (weekly)
- `DGS2` — 2Y Treasury

Response (HTTP 200):

- `as_of` — ISO-8601 UTC timestamp when the snapshot was built
- `metrics` — ordered list of `{"series_id", "label", "note", "value", "observation_date"}`. Per-metric `"error"` when that FRED fetch fails; `value` and `observation_date` are then `null`.

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/rates/key-metrics"
```

### Labor age metrics (`/api/economy/labor/age-metrics`)

Returns three BLS labor indicators, each broken out by age group (16–19, 20–24, 25–54, 55+), fetched in parallel from FRED:

| Metric | FRED series (by age order above) |
|--------|----------------------------------|
| Unemployment rate | `LNS14000012`, `LNS14000036`, `LNS14000060`, `LNS14024230` |
| Labor force participation | `LNS11300012`, `LNS11300036`, `LNS11300060`, `LNS11324230` |
| Employment-population ratio | `LNS12300012`, `LNS12300060` (direct); `LNS12300036` / `LNS12324230` computed from employment ÷ population levels (`LNS120*` / `LNU000*`) because FRED does not publish those ratio series |

**Default window:** YTD UTC; optional `observation_start` / `observation_end` (`YYYY-MM-DD`).

Response (HTTP 200):

- `start_date` / `end_date` — inclusive FRED window.
- `metrics` — ordered list of `{"id", "name", "series": [{"id", "age_group", "observations": [...]}]}`. Per-series `"error"` when FRED fails for that id only.

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/labor/age-metrics"
curl -sS "http://127.0.0.1:5001/api/economy/labor/age-metrics?observation_start=2024-01-01&observation_end=2024-12-31"
```

### OpenFEC candidate names (`/api/fec/candidates`)

Proxies OpenFEC **GET** [`/v1/names/candidates/`](https://api.open.fec.gov/developers/#/names/get_v1_names_candidates). The server sends **`api_key`** from `OPENFEC_API_KEY` only (never from the client).

Query parameters:

- **`q`** or **`name`** (alias): search string (required).
- **`page`**, **`per_page`**: forwarded when present; if **`per_page`** is omitted, the server defaults it to **5**.
- **`typeahead`**: when `1`, `true`, or `yes`, uses a shorter upstream timeout for responsive typeahead (debouncing belongs on the client).

Example (port **5001**):

```bash
curl -sS "http://127.0.0.1:5001/api/fec/candidates?q=smith"
```

### News routes

`GET /api/news/top-headlines` uses [GNews API v4](https://gnews.io/docs/v4). The server adds **`apikey`** from `GNEWS_API_KEY` only (never from the client).

#### `GET /api/news/top-headlines` (lazy loading)

Pagination uses **1-based `page`** and **`max`** as page size (sent to GNews). **Backward compatible:** omitting both behaves like **page 1**; omitting **`max`** alone defaults to **20** and caps at **50** (abuse clamp).

Optional **`offset`** (0-based): if you omit `page`, `offset` must be a **multiple of `max`**; the server derives `page = offset // max + 1`. If you send **both** `page` and `offset`, they must agree: `offset === (page - 1) * max`. Invalid combinations return **400** with a JSON `error` string.

The **`_`** query key (cache buster) is ignored and **not** forwarded upstream.

**Response (200):** `items` and `articles` are the **same** array (compat with parsers that expect either key). Pagination fields: `hasMore`, `nextPage`, `nextOffset`, `nextCursor` (always `null`; use `nextPage` / `nextOffset`), `page`, `max`, `total` (from GNews `totalArticles` when present). **`hasMore`** is false when this page returns **fewer than `max`** articles (partial last page) or when `total` implies there is no next page. Articles are **sorted** by `publishedAt` descending, then `url`, for stable ordering within the page.

**Ordering:** Within each page, results are sorted as above. Across pages, ordering follows GNews paging for the same `page` / `max` / filters.

Examples (port **5001**):

```bash
# First page (default max=20)
curl -sS "http://127.0.0.1:5001/api/news/top-headlines?lang=en"

# Page size 10, second page, optional category
curl -sS "http://127.0.0.1:5001/api/news/top-headlines?lang=en&max=10&page=2&category=technology"

# Same as page=2 with max=10 using offset
curl -sS "http://127.0.0.1:5001/api/news/top-headlines?lang=en&max=10&offset=10"

# Invalid offset (not a multiple of max) → 400
curl -sS "http://127.0.0.1:5001/api/news/top-headlines?max=20&offset=5"
```
