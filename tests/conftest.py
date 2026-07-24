"""Shared pytest fixtures (testing config, no reliance on ``app`` import side effects)."""

from __future__ import annotations

import pytest

from hypatia import create_app
from hypatia.extensions import db


@pytest.fixture
def app():
    return create_app("testing")


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.remove()
        db.drop_all()
