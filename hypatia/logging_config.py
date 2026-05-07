"""HTTP request correlation and access/upstream logging (no secrets in messages)."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from flask import Flask, g, has_request_context, request

from hypatia.settings import env_truthy


class RequestContextFilter(logging.Filter):
    """Attach ``request_id`` to log records when inside a Flask request."""

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "request_id") and getattr(record, "request_id", None) not in (
            None,
            "",
        ):
            return True
        if has_request_context():
            record.request_id = getattr(g, "request_id", "-")
        else:
            record.request_id = "-"
        return True


class HypatiaJsonFormatter(logging.Formatter):
    """One JSON object per line for records with ``event`` set; else plain text."""

    _EVENT_FIELDS = {
        "http_request": (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "request_id",
        ),
        "upstream": (
            "service",
            "endpoint",
            "status_code",
            "duration_ms",
            "request_id",
        ),
    }

    def __init__(
        self,
        *,
        datefmt: str | None = None,
        text_fallback: str | None = None,
    ) -> None:
        super().__init__(fmt="%(message)s", datefmt=datefmt)
        self._text_fallback = logging.Formatter(
            text_fallback
            or "%(asctime)s %(levelname)s [%(name)s] [req_id=%(request_id)s] %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        ev = getattr(record, "event", None)
        if isinstance(ev, str) and ev in self._EVENT_FIELDS:
            payload: dict[str, Any] = {
                "ts": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "event": ev,
            }
            for key in self._EVENT_FIELDS[ev]:
                if hasattr(record, key):
                    val = getattr(record, key)
                    if val is not None:
                        payload[key] = val
            payload["msg"] = record.getMessage()
            return json.dumps(payload, default=str)
        return self._text_fallback.format(record)


def configure_logging(app: Flask) -> None:
    """Apply LOG_LEVEL, LOG_FORMAT (``text`` | ``json``), and request context filter."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = os.environ.get("LOG_FORMAT", "text").strip().lower()
    if log_format == "json":
        datefmt = "%Y-%m-%dT%H:%M:%S"
        handler_fmt: logging.Formatter | HypatiaJsonFormatter = HypatiaJsonFormatter(
            datefmt=datefmt
        )
    else:
        datefmt = None
        handler_fmt = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] [req_id=%(request_id)s] %(message)s"
        )

    root = logging.getLogger()
    root.setLevel(level)

    if not any(getattr(h, "_hypatia_root", False) for h in root.handlers):
        h = logging.StreamHandler()
        h.setLevel(level)
        h.setFormatter(handler_fmt)
        h.addFilter(RequestContextFilter())
        h._hypatia_root = True  # type: ignore[attr-defined]
        root.addHandler(h)

    app.logger.setLevel(level)
    wk_level = logging.WARNING if level > logging.DEBUG else logging.DEBUG
    logging.getLogger("werkzeug").setLevel(wk_level)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _should_skip_access_log(path: str) -> bool:
    if env_truthy("LOG_VERBOSE_HEALTH", default=False):
        return False
    if not env_truthy("LOG_QUIET_HEALTH", default=True):
        return False
    return path in ("/health", "/hello")


def register_request_logging(app: Flask) -> None:
    """Request ID (header or generated), X-Request-ID on response, access log line."""

    @app.before_request
    def _assign_request_id() -> None:
        raw = request.headers.get("X-Request-ID", "").strip()
        g.request_id = raw if raw else str(uuid.uuid4())
        g._access_start = time.perf_counter()

    @app.after_request
    def _log_request_and_header(response):
        try:
            rid = getattr(g, "request_id", None) or "-"
            response.headers["X-Request-ID"] = rid
            if _should_skip_access_log(request.path):
                return response
            start = getattr(g, "_access_start", None)
            duration_ms = (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
            app.logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "request_id": rid,
                    "method": request.method,
                    "path": request.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        except Exception:
            pass
        return response


def log_upstream(
    logger_name: str,
    *,
    service: str,
    endpoint: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """Log an outbound HTTP call (no URLs, query strings, or API keys)."""
    log = logging.getLogger(logger_name)
    rid = None
    if has_request_context():
        rid = getattr(g, "request_id", None)
    log.info(
        "upstream",
        extra={
            "event": "upstream",
            "service": service,
            "endpoint": endpoint,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "request_id": rid,
        },
    )
