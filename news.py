"""GNews API v4 helpers (https://gnews.io/docs/v4)."""

from typing import Any

import requests

GNEWS_BASE = "https://gnews.io/api/v4"

# Query params forwarded from our routes (apikey is never taken from the client).
TOP_HEADLINES_PARAMS = frozenset(
    {
        "category",
        "lang",
        "country",
        "max",
        "nullable",
        "from",
        "to",
        "q",
        "page",
        "truncate",
    }
)
SEARCH_PARAMS = frozenset(
    {
        "q",
        "lang",
        "country",
        "max",
        "in",
        "nullable",
        "from",
        "to",
        "sortby",
        "page",
    }
)


def filter_query_args(args, allowed: frozenset[str]) -> dict[str, str]:
    """Keep only whitelisted query keys with non-empty values."""
    out: dict[str, str] = {}
    for k in allowed:
        v = args.get(k)
        if v is None:
            continue
        s = v.strip() if isinstance(v, str) else str(v).strip()
        if not s:
            continue
        out[k] = s
    return out


def fetch_gnews(
    path: str,
    query: dict[str, str],
    api_key: str,
    *,
    timeout: float = 30.0,
) -> tuple[Any, int]:
    """GET /api/v4/{path} with server-side apikey. Returns (parsed JSON body, HTTP status)."""
    params = {**query, "apikey": api_key}
    url = f"{GNEWS_BASE}/{path.lstrip('/')}"
    resp = requests.get(url, params=params, timeout=timeout)
    try:
        data = resp.json()
    except ValueError:
        return {"error": "Invalid response from GNews API"}, 502
    return data, resp.status_code
