"""Tests for health check endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
    os.environ.setdefault("DATABASE_URL_SYNC", "sqlite://")
    from reasons_service.app import app
    from reasons_service.db.connection import get_session

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_session.execute.return_value = mock_result
    app.dependency_overrides[get_session] = lambda: mock_session

    yield TestClient(app), mock_session

    app.dependency_overrides.pop(get_session, None)


class TestHealthEndpoints:

    def test_healthz_returns_ok(self, client):
        test_client, _ = client
        resp = test_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readyz_returns_ready(self, client):
        test_client, _ = client
        resp = test_client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    def test_readyz_returns_503_on_db_failure(self, client):
        test_client, mock_session = client
        mock_session.execute.side_effect = Exception("connection refused")
        resp = test_client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not ready"

    def test_healthz_no_auth_required(self, client):
        test_client, _ = client
        resp = test_client.get("/healthz")
        assert resp.status_code == 200

    def test_readyz_no_auth_required(self, client):
        test_client, _ = client
        resp = test_client.get("/readyz")
        assert resp.status_code == 200
