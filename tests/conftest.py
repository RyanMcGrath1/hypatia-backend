"""Shared pytest fixtures (testing config, no reliance on ``app`` import side effects)."""

from __future__ import annotations

import pytest

from hypatia import create_app


@pytest.fixture
def app():
    return create_app("testing")


@pytest.fixture
def client(app):
    return app.test_client()
