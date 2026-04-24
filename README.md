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

Copy [.env.example](.env.example) to `.env` and set `GOOGLE_CIVIC_API_KEY`. Never commit `.env`.

Optional environment variables:

- `EXPO_CORS_EXTRA_ORIGINS` — comma-separated extra CORS origins for Expo web
- `PORT` — listen port when using `python app.py` (default `5000`)

## Run locally

Development (binds `0.0.0.0` so LAN devices can reach the server):

```bash
python app.py
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
| GET | `/api/civic/representatives?address=...` | Proxies Google Civic representatives lookup |

If `GOOGLE_CIVIC_API_KEY` is missing, the civic route returns `503` with a JSON error body.
