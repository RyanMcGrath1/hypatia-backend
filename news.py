"""GNews API v4 helpers (https://gnews.io/docs/v4)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

from hypatia.logging_config import log_upstream

GNEWS_BASE = "https://gnews.io/api/v4"

# Top headlines: optional filters forwarded to GNews (not page/max/offset; those are handled below).
TOP_HEADLINES_UPSTREAM_PARAMS = frozenset(
    {
        "category",
        "lang",
        "country",
        "nullable",
        "from",
        "to",
        "q",
        "truncate",
    }
)

TOP_HEADLINES_PAGE_SIZE_DEFAULT = 20
TOP_HEADLINES_PAGE_SIZE_MAX = 50
TOP_HEADLINES_PAGE_SIZE_MIN = 1

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
    t0 = time.perf_counter()
    resp = requests.get(url, params=params, timeout=timeout)
    log_upstream(
        "hypatia.upstream",
        service="gnews",
        endpoint=path.lstrip("/"),
        status_code=resp.status_code,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    try:
        data = resp.json()
    except ValueError:
        return {"error": "Invalid response from GNews API"}, 502
    return data, resp.status_code


def _parse_positive_int(
    name: str,
    raw: str | None,
    *,
    default: int | None,
    minimum: int,
    maximum: int,
) -> tuple[int | None, str | None]:
    """Return (value, error_message). error_message set on failure."""
    if raw is None or not str(raw).strip():
        if default is None:
            return None, f"Query parameter '{name}' is required"
        v = default
    else:
        s = str(raw).strip()
        try:
            v = int(s, 10)
        except ValueError:
            return None, f"Query parameter '{name}' must be an integer"
    if v < minimum:
        return None, f"Query parameter '{name}' must be >= {minimum}"
    if v > maximum:
        v = maximum
    return v, None


def _published_at_sort_key(article: dict) -> tuple[float, str]:
    """Newer first, then stable tie-break on url."""
    p = article.get("publishedAt") or ""
    url = article.get("url") or ""
    if not p:
        return (0.0, url)
    try:
        p2 = p.replace("Z", "+00:00")
        dt = datetime.fromisoformat(p2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = dt.timestamp()
    except (ValueError, TypeError, OSError):
        ts = 0.0
    return (-ts, url)


def _stable_sort_headlines(articles: list) -> list:
    return sorted(articles, key=lambda a: _published_at_sort_key(a if isinstance(a, dict) else {}))


def parse_top_headlines_pagination(args) -> tuple[int, int, str | None]:
    """Resolve page (1-based) and max (page size). Returns (page, max, error_message)."""
    max_raw = args.get("max")
    page_raw = args.get("page")
    offset_raw = args.get("offset")

    max_size, err = _parse_positive_int(
        "max",
        max_raw,
        default=TOP_HEADLINES_PAGE_SIZE_DEFAULT,
        minimum=TOP_HEADLINES_PAGE_SIZE_MIN,
        maximum=TOP_HEADLINES_PAGE_SIZE_MAX,
    )
    if err:
        return 0, 0, err

    has_page = page_raw is not None and str(page_raw).strip() != ""
    has_offset = offset_raw is not None and str(offset_raw).strip() != ""

    if has_page and has_offset:
        page, err = _parse_positive_int("page", page_raw, default=None, minimum=1, maximum=10**9)
        if err:
            return 0, 0, err
        try:
            offset = int(str(offset_raw).strip(), 10)
        except ValueError:
            return 0, 0, "Query parameter 'offset' must be an integer"
        if offset < 0:
            return 0, 0, "Query parameter 'offset' must be >= 0"
        expected = (page - 1) * max_size
        if offset != expected:
            msg = (
                f"Query parameters 'page' and 'offset' disagree: "
                f"for page={page} and max={max_size}, offset must be {expected}"
            )
            return (0, 0, msg)
        return page, max_size, None

    if has_offset:
        try:
            offset = int(str(offset_raw).strip(), 10)
        except ValueError:
            return 0, 0, "Query parameter 'offset' must be an integer"
        if offset < 0:
            return 0, 0, "Query parameter 'offset' must be >= 0"
        if offset % max_size != 0:
            msg = (
                f"Query parameter 'offset' must be a multiple of max ({max_size}) "
                "when 'page' is omitted"
            )
            return (0, 0, msg)
        page = offset // max_size + 1
        return page, max_size, None

    if has_page:
        page, err = _parse_positive_int("page", page_raw, default=None, minimum=1, maximum=10**9)
        if err:
            return 0, 0, err
        return page, max_size, None

    return 1, max_size, None


def build_top_headlines_envelope(
    args,
    api_key: str,
    *,
    timeout: float = 30.0,
) -> tuple[Any, int]:
    """GET top-headlines with page/max pagination and a stable client-facing envelope.

    Pagination model: **1-based ``page``** and **``max``** page size (forwarded to GNews).
    Optional **0-based ``offset``** (must be ``(page-1)*max``) is accepted as an alternative
    to ``page`` when the two are consistent, or alone when it is a multiple of ``max``.

    Response (HTTP 200): ``items`` / ``articles`` (same array), ``hasMore``, ``nextPage``,
    ``nextOffset``, ``nextCursor`` (always null; use ``nextPage``), ``page``, ``max``, ``total``.
    """
    page, max_size, err = parse_top_headlines_pagination(args)
    if err:
        return ({"error": err}, 400)

    upstream = filter_query_args(args, TOP_HEADLINES_UPSTREAM_PARAMS)
    upstream["page"] = str(page)
    upstream["max"] = str(max_size)

    raw, status = fetch_gnews("top-headlines", upstream, api_key, timeout=timeout)
    if status != 200:
        return raw, status

    articles = raw.get("articles") if isinstance(raw, dict) else None
    if not isinstance(articles, list):
        articles = []
    articles = [a for a in articles if isinstance(a, dict)]
    articles = _stable_sort_headlines(articles)

    total = raw.get("totalArticles") if isinstance(raw, dict) else None
    if total is not None:
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = None

    n = len(articles)
    consumed_end = (page - 1) * max_size + n
    if n < max_size:
        # Partial page from upstream — no further full pages for this page size.
        has_more = False
    elif total is not None:
        has_more = consumed_end < total
    else:
        # Full page and unknown total — assume more may exist.
        has_more = True

    next_page = (page + 1) if has_more else None
    next_offset = (page * max_size) if has_more else None

    payload: dict[str, Any] = {
        "items": articles,
        "articles": articles,
        "hasMore": has_more,
        "nextPage": next_page,
        "nextOffset": next_offset,
        "nextCursor": None,
        "page": page,
        "max": max_size,
        "total": total,
    }
    return payload, 200
