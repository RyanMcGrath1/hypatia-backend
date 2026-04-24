# hypatia-backend

Flask API for Hypatia (Google Civic Information proxy and health checks).

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

Copy [.env.example](.env.example) to `.env` and set `GOOGLE_CIVIC_API_KEY`. Never commit `.env`.

Optional environment variables:

- `FRED_API_KEY` — [FRED (Federal Reserve Economic Data)](https://fred.stlouisfed.org/docs/api/api_key.html) API key; reserved for future FRED-backed routes (not read by the app yet)
- `EXPO_CORS_EXTRA_ORIGINS` — comma-separated extra CORS origins for Expo web
- `PORT` — listen port when using `python app.py` (default `5000`)
- `FLASK_DEBUG` or `DEBUG` — set to `1`, `true`, or `yes` to enable Flask’s debug mode and reloader when running `python app.py` (default is off)

## Run locally

Development (binds `0.0.0.0` so LAN devices can reach the server). Enable the debugger with `FLASK_DEBUG=1` (PowerShell: `$env:FLASK_DEBUG='1'; python app.py`):

```bash
python app.py
```

Run tests:

```bash
pytest
```

Or with the Flask CLI:

```bash
flask --app app run --host 0.0.0.0 --port 5000
```

## Production (WSGI)

Use [wsgi.py](wsgi.py) with Gunicorn:

```bash
gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app
```

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Plain text hello |
| GET | `/hello` | JSON smoke check |
| GET | `/health` | Same JSON as `/hello` (load balancers) |
| GET | `/api/civic/divisions-by-address?address=...` | Proxies [Google Civic `divisionsByAddress`](https://developers.google.com/civic-information/docs/v2/divisions/divisionsByAddress) (OCD division IDs for an address) |
| GET | `/api/civic/representatives?...` | **410 Gone** — Google removed the Representatives API in 2025; use `/api/civic/divisions-by-address` instead |

If `GOOGLE_CIVIC_API_KEY` is missing, the civic route returns `503` with a JSON body whose `error` is `Missing GOOGLE_CIVIC_API_KEY`. **Fix:** put the key in `.env` next to `app.py`, then **fully stop and restart** the Flask process (debug mode’s reloader still needs a restart after you first create `.env`).

### Google Civic API note

The **Representatives** lookup was [turned down](https://groups.google.com/g/google-civicinfo-api/c/9fwFn-dhktA) after **April 30, 2025**. This service uses **`divisionsByAddress`**, which returns division names and OCD IDs; you can use those IDs with other datasets if you need officeholder lists. See [Civic Information API](https://developers.google.com/civic-information/docs/v2).
