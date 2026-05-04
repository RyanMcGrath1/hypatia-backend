# hypatia-backend

Flask API for Hypatia (Google Civic Information proxy, FRED-backed economy summary, GNews proxy for headlines and search, and health checks).

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

Copy [.env.example](.env.example) to `.env` and set `GOOGLE_CIVIC_API_KEY`, `FRED_API_KEY` (economy routes), and `GNEWS_API_KEY` (news routes) as needed. Never commit `.env`.

**API keys**

- `GOOGLE_CIVIC_API_KEY` — Google Cloud; required for `GET /api/civic/divisions-by-address`
- `FRED_API_KEY` — [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html) key from [your FRED account](https://fredaccount.stlouisfed.org/apikeys); required for `GET /api/economy/summary`
- `GNEWS_API_KEY` — [GNews](https://gnews.io/) API key; required for `GET /api/news/top-headlines` and `GET /api/news/search`

Optional environment variables:

- `EXPO_CORS_EXTRA_ORIGINS` — comma-separated extra allowed origins (e.g. tunnel URLs like ngrok)
- `CORS_ALLOW_ALL_ORIGINS` — set to `1`, `true`, or `yes` to allow **any** `Origin` (local debugging only; never in production)
- `PORT` — listen port when using `python app.py` (default `5001`; macOS often reserves `5000` for AirPlay Receiver)
- `FLASK_DEBUG` or `DEBUG` — set to `1`, `true`, or `yes` to enable Flask’s debug mode and reloader when running `python app.py` (default is off)
- `LOG_LEVEL` — Python logging level (default `INFO`; use `DEBUG` for more detail)
- `LOG_FORMAT` — `text` (default) or `json` (one JSON object per line for log aggregators)
- `LOG_QUIET_HEALTH` — when `1` (default), skip access-style log lines for `/health` and `/hello` at INFO; set `LOG_VERBOSE_HEALTH=1` to log them
- `LOG_VERBOSE_HEALTH` — if `1`, log health routes even when quiet health is on (overrides the skip)

### Logging

Each request gets a **`X-Request-ID`** (from the incoming `X-Request-ID` header or generated). The same value is returned on the response; CORS **exposes** this header for browser clients. Access logs include method, path, status, and duration (ms). Outbound calls to **GNews** and **Google Civic** log service name, endpoint label, status, and duration—**never** full URLs, query strings, or API keys. FRED tile failures log **warnings** with `tile_id` / `series_id` only.

### CORS (Expo on your PC and on a phone)

The API listens on `0.0.0.0`, so on your phone use your computer’s **LAN IP** and port (e.g. `http://192.168.1.71:5001`). CORS allows typical Expo/Metro dev origins: `localhost` / `127.0.0.1` on any port, and `http://<private-LAN-ip>:<port>` (so when the phone loads the bundle from `http://192.168.x.x:8081`, browser preflights still succeed). For tunnels or odd origins, add them to `EXPO_CORS_EXTRA_ORIGINS`. If something still blocks requests during local dev only, set `CORS_ALLOW_ALL_ORIGINS=1` in `.env`.

## Run locally

Development (binds `0.0.0.0` so LAN devices can reach the server). Enable the debugger with `FLASK_DEBUG=1` (PowerShell: `$env:FLASK_DEBUG='1'; python app.py`):

```bash
python app.py
```

With no `PORT` in `.env`, the server listens on **5001** (see optional env vars above). Use `source .venv/bin/activate` before `python app.py` if `python` is not on your PATH.

Run tests:

```bash
pytest
```

Or with the Flask CLI:

```bash
flask --app app run --host 0.0.0.0 --port 5001
```

## Production (WSGI)

Use [wsgi.py](wsgi.py) with Gunicorn:

```bash
gunicorn -w 2 -b 0.0.0.0:5001 wsgi:app
```

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Plain text hello |
| GET | `/hello` | JSON smoke check |
| GET | `/health` | Same JSON as `/hello` (load balancers) |
| GET | `/api/civic/divisions-by-address?address=...` | Proxies [Google Civic `divisionsByAddress`](https://developers.google.com/civic-information/docs/v2/divisions/divisionsByAddress) (OCD division IDs for an address) |
| GET | `/api/civic/representatives?...` | **410 Gone** — Google removed the Representatives API in 2025; use `/api/civic/divisions-by-address` instead |
| GET | `/api/economy/summary` | Latest FRED observations for configured economy tiles (`cpi_all_items`, `unemployment_rate`, `federal_funds_effective`); JSON has `as_of` and `tiles` |
| GET | `/api/news/top-headlines` | [GNews top headlines](https://docs.gnews.io/endpoints/top-headlines-endpoint) with **page/max pagination** and a stable JSON envelope; see [News routes](#news-routes) |
| GET | `/api/news/search` | Proxies [GNews search](https://docs.gnews.io/endpoints/search-endpoint); requires `q`; see [News routes](#news-routes) |

If `GOOGLE_CIVIC_API_KEY` is missing, the civic route returns `503` with a JSON body whose `error` is `Missing GOOGLE_CIVIC_API_KEY`. **Fix:** put the key in `.env` next to `app.py`, then **fully stop and restart** the Flask process (debug mode’s reloader still needs a restart after you first create `.env`). News routes return **503** with `Missing GNEWS_API_KEY` when `GNEWS_API_KEY` is unset.

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
