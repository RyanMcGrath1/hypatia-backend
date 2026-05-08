# hypatia-backend

Flask API for Hypatia (Google Civic Information proxy, FRED-backed economy summary and overview, OpenFEC candidate name search proxy, GNews proxy for headlines and search, and health checks).

## Project layout

| Path | Role |
|------|------|
| [app.py](app.py) | Dev entrypoint: `create_app()` + `python app.py` (re-exports `app` for `flask --app app`). |
| [wsgi.py](wsgi.py) | WSGI entry: `application = create_app()` for Gunicorn (`wsgi:application` or alias `wsgi:app`). |
| [hypatia/](hypatia/__init__.py) | Application factory ([`create_app`](hypatia/__init__.py)), [settings](hypatia/settings.py) (`development` / `production` / `testing`), [CORS](hypatia/cors.py), [logging](hypatia/logging_config.py), [HTTP helpers](hypatia/http.py), [JSON error handlers](hypatia/error_handlers.py). |
| [hypatia/routes/](hypatia/routes/__init__.py) | Flask blueprints (health, civic, FEC, economy, news). |
| [economy.py](economy.py), [news.py](news.py) | FRED and GNews client logic (root modules; imported by blueprints). |
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
- `FRED_API_KEY` — [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html) key from [your FRED account](https://fredaccount.stlouisfed.org/apikeys); required for economy routes (`GET /api/economy/summary`, `GET /api/economy/overview`, `GET /api/economy/fred/observations`)
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
- `LOG_QUIET_HEALTH` — when truthy (default `1`), skip access-style log lines for `/health` and `/hello` at INFO; set `LOG_VERBOSE_HEALTH` to log them
- `LOG_VERBOSE_HEALTH` — if truthy, log health routes even when quiet health is on (overrides the skip). Truthy values: `1`, `true`, `yes`, `on`

### Logging

Hypatia’s **text** logs use colors by default on interactive terminals (level, timestamp, logger name, request id). JSON logs stay plain for parsers. Control with **`LOG_COLOR`** (`auto` | `always` | `never`).

Each request gets a **`X-Request-ID`** (from the incoming `X-Request-ID` header or generated). The same value is returned on the response; CORS **exposes** this header for browser clients. Access logs include method, path, status, and duration (ms). Outbound calls to **GNews**, **Google Civic**, **OpenFEC**, and **FRED** (including the observations proxy) log service name, endpoint label, status, and duration—**never** full URLs, query strings, or API keys. FRED tile failures inside the summary/overview builders still log **warnings** with `tile_id` / `series_id` only.

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
| GET | `/` | Plain text hello |
| GET | `/hello` | JSON smoke check |
| GET | `/health` | Same JSON as `/hello` (load balancers) |
| GET | `/api/civic/divisions-by-address?address=...` | Proxies [Google Civic `divisionsByAddress`](https://developers.google.com/civic-information/docs/v2/divisions/divisionsByAddress) (OCD division IDs for an address) |
| GET | `/api/civic/representatives?...` | **410 Gone** — Google removed the Representatives API in 2025; use `/api/civic/divisions-by-address` instead |
| GET | `/api/economy/summary` | Latest FRED observations for configured economy tiles (`cpi_all_items`, `unemployment_rate`, `federal_funds_effective`); JSON has `as_of` and `tiles` |
| GET | `/api/economy/overview` | Recent FRED observations per overview series; JSON has `as_of` and `sections` (see [Economy overview](#economy-overview-apieconomyoverview)) |
| GET | `/api/economy/fred/observations?series_id=...` | Proxies [FRED `series/observations`](https://fred.stlouisfed.org/docs/api/fred/series_observations.html); `api_key` from env only; optional `observation_start`, `sort_order`, `limit` (default 60, max 10000) |
| GET | `/api/economy/fred/series/PAYEMS/delta` | PAYEMS-only monthly deltas via FRED observations (`units=chg`); optional `observation_start`, `sort_order`, `limit` |
| GET | `/api/fec/v1/names/candidates?...` | Proxies [OpenFEC `names/candidates`](https://api.open.fec.gov/developers/#/names/get_v1_names_candidates); `api_key` from env only; alias path below |
| GET | `/api/fec/candidates?...` | Same as `/api/fec/v1/names/candidates` (backward-compatible alias) |
| GET | `/api/news/top-headlines` | [GNews top headlines](https://docs.gnews.io/endpoints/top-headlines-endpoint) with **page/max pagination** and a stable JSON envelope; see [News routes](#news-routes) |
| GET | `/api/news/search` | Proxies [GNews search](https://docs.gnews.io/endpoints/search-endpoint); requires `q`; see [News routes](#news-routes) |

If `GOOGLE_CIVIC_API_KEY` is missing, the civic route returns `503` with a JSON body whose `error` is `Missing GOOGLE_CIVIC_API_KEY`. **Fix:** put the key in `.env` at the **repository root** (same directory as `app.py`), then **fully stop and restart** the Flask process (debug mode’s reloader still needs a restart after you first create `.env`). Economy routes that need FRED return **503** with `Missing FRED_API_KEY` when `FRED_API_KEY` is unset. News routes return **503** with `Missing GNEWS_API_KEY` when `GNEWS_API_KEY` is unset. OpenFEC routes return **503** with `Missing OPENFEC_API_KEY` when `OPENFEC_API_KEY` is unset.

Unknown paths return **404** with JSON `{"error": "Not Found"}`. Unhandled server errors return **500** with JSON `{"error": "Internal Server Error"}`.

### Economy summary (`/api/economy/summary`)

Returns **HTTP 200** with:

- `as_of`: ISO-8601 UTC timestamp when the snapshot was built.
- `tiles`: object keyed by `tile_id`. Each value is either a success object (`label`, `series_id`, `unit`, `value`, `observation_date`, and optionally `change`, `prior_observation_date`) or an error object (`error`, optional `hint`) if that series failed.

If `FRED_API_KEY` is missing, the route returns **503** with `error` `Missing FRED_API_KEY` (same pattern as the civic key).

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/summary"
```

(PowerShell: `curl.exe` if `curl` is aliased to `Invoke-WebRequest`.)

### Economy overview (`/api/economy/overview`)

Returns **HTTP 200** with:

- `as_of`: ISO-8601 UTC timestamp when the snapshot was built.
- `sections`: object keyed by section; each value holds recent FRED observations for that overview series (newest first within each section).

Uses the same `FRED_API_KEY` as `/api/economy/summary`. If the key is missing, the route returns **503** with `Missing FRED_API_KEY`.

Example:

```bash
curl -sS "http://127.0.0.1:5001/api/economy/overview"
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
