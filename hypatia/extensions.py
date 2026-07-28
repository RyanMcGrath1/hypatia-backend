"""Flask extension instances (initialized in :func:`hypatia.create_app`)."""

from __future__ import annotations

import sqlite3

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()

# No default/global limits — auth routes attach explicit per-route limits.
# Storage URI comes from app config (memory:// for development/tests; shared
# backend such as Redis for multi-worker production).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enable SQLite foreign-key enforcement (off by default in SQLite)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
