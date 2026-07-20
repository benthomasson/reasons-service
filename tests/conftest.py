"""Shared fixtures for expert-service tests."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reasons_service.api.ask import router as ask_router


@pytest.fixture
def ask_app():
    app = FastAPI()
    app.include_router(ask_router)
    return app


@pytest.fixture
def client(ask_app):
    return TestClient(ask_app)


@pytest.fixture
def mock_search():
    with patch("reasons_service.api.ask.rms_api.search") as m:
        yield m


VALID_DOMAIN_ID = "00000000-0000-0000-0000-000000000001"
