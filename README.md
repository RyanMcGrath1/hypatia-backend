# hypatia-backend

Flask API for Hypatia (Google Civic Information proxy, FRED-backed economy dashboard, OpenFEC candidate name search proxy, GNews proxy for headlines and search, and health checks).

## Project layout

| Path | Role |
|------|------|
| [app.py](app.py) | Dev entrypoint: `create_app()` + `python app.py` (re-exports `app` for `flask --app app`). |
| [wsgi.py](wsgi.py) | WSGI entry: `application = create_app()` for Gunicorn (`wsgi:application` or alias `wsgi:app`). |
| [hypatia/](hypatia/__init__.py) | Application factory ([`create_app`](hypatia/__init__.py)), [settings](hypatia/settings.py) (`development` / `production` / `testing`), [CORS](hypatia/cors.py), [logging](hypatia/logging_config.py), [HTTP helpers](hypatia/http.py), [JSON error handlers](hypatia/error_handlers.py). |
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

Copy [.env.example](.env.example) to `.env` and set `GOOGLE_CIVIC_API_KEY`, `FRED_API_KEY` (economy routes), `GNEWS_API_KEY` (news routes), and `OPENFEC_API_KEY` (FEC routes) as needed. Never commit `.env`.

**API keys**

- `GOOGLE_CIVIC_API_KEY` — Google Cloud; required for `GET /api/civic/divisions-by-address`
- `FRED_API_KEY` — [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html) key from [your FRED account](https://fredaccount.stlouisfed.org/apikeys); required for economy routes (`GET /api/economy/dashboard`, `GET /api/economy/<sector>/dashboard`, `GET /api/economy/labor/sector`, `GET /api/economy/fred/observations`, `GET /api/economy/fred/series/PAYEMS/delta`)
- `GNEWS_API_KEY` — [GNews](https://gnews.io/) API key; required for `GET /api/news/top-headlines` and `GET /api/news/search`
- `OPENFEC_API_KEY` — [OpenFEC](https://api.open.fec.gov/developers/) API key; required for `GET /api/fec/v1/names/candidates` and the alias `GET /api/fec/candidates`

Optional environment variables:

- `HYPATIA_ENV` or `FLASK_ENV` — `development` (default), `production`, or `testing` (pytest uses `testing` via the app factory; not usually set by hand)
- `SECRET_KEY` — set in production for signed cookies and similar; a dev-only default is used if unset (see [hypatia/settings.py](hypatia/settings.py))
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

Each request gets a **`X-Request-ID`** (from the incoming `X-Request-ID` header or generated). The same value is returned on the response; CORS **exposes** this header for browser clients. Access logs include method, path, status, and duration (ms). Outbound calls to **GNews**, **Google Civic**, **OpenFEC**, and **FRED** (including the observations proxy) log service name, endpoint label, status, and duration—**never** full URLs, query strings, or API keys. FRED failures inside the economy dashboard builders still log **warnings** with `section_key` / `series_id` only.

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
| GET | `/api/civic/divisions-by-address?address=...` | Proxies [Google Civic `divisionsByAddress`](https://developers.google.com/civic-information/docs/v2/divisions/divisionsByAddress) (OCD division IDs for an address) |
| GET | `/api/civic/representatives?...` | **410 Gone** — Google removed the Representatives API in 2025; use `/api/civic/divisions-by-address` instead |
| GET | `/api/economy/detail?topic=...` | Premium economy detail screens (`topic`: `gdp`, `labor`, `inflation`, `markets`); JSON has `charts`, `headline`, `as_of` (Expo `economyDetailApi`) |
| GET | `/api/economy/dashboard` | Economy tab snapshot: recent FRED observations per section; JSON has `as_of` and `sections` (see [Economy dashboard](#economy-dashboard-apieconomydashboard)) |
| GET | `/api/economy/<sector>/dashboard` | One overview section (same `sections` entry shape as `GET /api/economy/dashboard`); `sector` is a section key or app alias (`consumer` → `consumer_spending`, `rates` → `interest_rates`). **Default window:** year-to-date in UTC (Jan 1 through today) when `observation_start` and `observation_end` are omitted. Optional **`observation_start`** / **`observation_end`** (`YYYY-MM-DD`) narrow the FRED observation window; invalid or inverted ranges return **400**. Response echoes **`observation_start`** and **`observation_end`**. Not the same as `GET /api/economy/labor/sector` (payroll-by-industry chart). |
| GET | `/api/economy/labor/sector` | Employment levels across sixteen FRED payroll series; JSON has `start_date`, `end_date`, and `series` (see [Labor employment by sector](#labor-employment-by-sector-apieconomylaborsector)). **Default window:** YTD UTC, same rules as `<sector>/dashboard`. |
| GET | `/api/economy/labor/earnings-inflation` | `CES0500000003` (average hourly earnings) and `CPIAUCSL` (CPI inflation); same JSON shape as `labor/sector` (see [Labor earnings and CPI](#labor-earnings-and-cpi-apieconomylaborearnings-inflation)) |
| GET | `/api/economy/labor/age-metrics` | Unemployment, labor force participation, and employment-population ratio by age cohort (12 FRED `LNS*` series); see [Labor age metrics](#labor-age-metrics-apieconomylaborage-metrics) |
| GET | `/api/economy/fred/observations?series_id=...` | Proxies [FRED `series/observations`](https://fred.stlouisfed.org/docs/api/fred/series_observations.html); `api_key` from env only; optional `observation_start`, `sort_order`, `limit` (default 60, max 10000) |
| GET | `/api/economy/fred/series/PAYEMS/delta` | PAYEMS-only monthly deltas via FRED observations (`units=chg`); optional `observation_start`, `observation_end`, `sort_order`, `limit` |
| GET | `/api/fec/v1/names/candidates?...` | Proxies [OpenFEC `names/candidates`](https://api.open.fec.gov/developers/#/names/get_v1_names_candidates); `api_key` from env only; alias path below |
| GET | `/api/fec/candidates?...` | Same as `/api/fec/v1/names/candidates` (backward-compatible alias) |
| GET | `/api/news/top-headlines` | [GNews top headlines](https://docs.gnews.io/endpoints/top-headlines-endpoint) with **page/max pagination** and a stable JSON envelope; see [News routes](#news-routes) |
| GET | `/api/news/search` | Proxies [GNews search](https://docs.gnews.io/endpoints/search-endpoint); requires `q`; see [News routes](#news-routes) |

If `GOOGLE_CIVIC_API_KEY` is missing, the civic route returns `503` with a JSON body whose `error` is `Missing GOOGLE_CIVIC_API_KEY`. **Fix:** put the key in `.env` at the **repository root** (same directory as `app.py`), then **fully stop and restart** the Flask process (debug mode’s reloader still needs a restart after you first create `.env`). Economy routes that need FRED return **503** with `Missing FRED_API_KEY` when `FRED_API_KEY` is unset. News routes return **503** with `Missing GNEWS_API_KEY` when `GNEWS_API_KEY` is unset. OpenFEC routes return **503** with `Missing OPENFEC_API_KEY` when `OPENFEC_API_KEY` is unset.

Unknown paths return **404** with JSON `{"error": "Not Found"}`. Unhandled server errors return **500** with JSON `{"error": "Internal Server Error"}`.

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

### FRED series observations (`/api/economy/fred/observations`)

Thin proxy for [FRED `series/observations`](https://fred.stlouisfed.org/docs/api/fred/series_observations.html). The server supplies **`api_key`** from **`FRED_API_KEY`** and **`file_type=json`**. **`series_id`** is required. **`observation_start`** is optional (omit it and use **`sort_order=desc`** with **`limit`** to pull the most recent points). Optional **`limit`** defaults to **60** and is capped at **10000**. Additional whitelisted parameters (e.g. `observation_end`, `sort_order`, `offset`) are forwarded when present.

Example (port **5001**, latest `PAYEMS` prints):

```bash
curl -sS "http://127.0.0.1:5001/api/economy/fred/observations?series_id=PAYEMS&limit=72&sort_order=desc"
```

With an explicit window:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/fred/observations?series_id=PAYEMS&observation_start=2020-01-01&limit=60"
```

### PAYEMS monthly deltas (`/api/economy/fred/series/PAYEMS/delta`)

Returns PAYEMS month-over-month deltas directly from FRED (`units=chg`) so clients do not need to subtract levels manually. The server still injects `api_key` and `file_type=json`. Optional query params include `observation_start`, `limit`, and `sort_order`.

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/fred/series/PAYEMS/delta?limit=72&sort_order=desc"
```

### Labor employment by sector (`/api/economy/labor/sector`)

Returns employment **levels** (not the unemployment-rate slice from `GET /api/economy/labor/dashboard`) for a fixed set of FRED payroll series, fetched in parallel.

**Default window:** year-to-date in UTC (`Jan 1` through `today`), same as `GET /api/economy/<sector>/dashboard`. Optional **`observation_start`** / **`observation_end`** (`YYYY-MM-DD`, inclusive) override; invalid or inverted ranges return **400**.

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

### OpenFEC candidate names (`/api/fec/v1/names/candidates` and `/api/fec/candidates`)

Proxies OpenFEC **GET** [`/v1/names/candidates/`](https://api.open.fec.gov/developers/#/names/get_v1_names_candidates). The server sends **`api_key`** from `OPENFEC_API_KEY` only (never from the client).

Query parameters:

- **`q`** or **`name`** (alias): search string (required).
- **`page`**, **`per_page`**: forwarded when present; if **`per_page`** is omitted, the server defaults it to **5**.
- **`typeahead`**: when `1`, `true`, or `yes`, uses a shorter upstream timeout for responsive typeahead (debouncing belongs on the client).

Examples (port **5001**):

```bash
curl -sS "http://127.0.0.1:5001/api/fec/candidates?q=smith"
curl -sS "http://127.0.0.1:5001/api/fec/v1/names/candidates?name=jane%20doe&typeahead=1"
```

### News routes

Both routes use [GNews API v4](https://gnews.io/docs/v4). The server adds **`apikey`** from `GNEWS_API_KEY` only (never from the client).

#### `GET /api/news/search`

Query parameters are **whitelisted and forwarded** to GNews as before (for example `q` required, optional `lang`, `max`, …). Omitting `max` leaves it to GNews defaults.

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

curl -sS "http://127.0.0.1:5001/api/news/search?q=climate&lang=en"
```

### Google Civic API note

The **Representatives** lookup was [turned down](https://groups.google.com/g/google-civicinfo-api/c/9fwFn-dhktA) after **April 30, 2025**. This service uses **`divisionsByAddress`**, which returns division names and OCD IDs; you can use those IDs with other datasets if you need officeholder lists. See [Civic Information API](https://developers.google.com/civic-information/docs/v2).
