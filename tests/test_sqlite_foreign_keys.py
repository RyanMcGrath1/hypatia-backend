"""SQLite foreign-key enforcement for Flask-SQLAlchemy connections."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from hypatia.extensions import db
from hypatia.models import Profile


def test_sqlite_foreign_keys_pragma_is_on(app) -> None:
    with app.app_context():
        assert db.engine.dialect.name == "sqlite"

        with db.engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_sqlite_rejects_profile_with_missing_user(app) -> None:
    with app.app_context():
        db.create_all()

        profile = Profile(
            user_id=uuid.uuid4(),
            first_name="Ada",
            last_name="Lovelace",
        )
        db.session.add(profile)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()
