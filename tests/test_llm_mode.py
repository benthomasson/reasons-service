"""Tests for LLM / no-LLM mode toggle (EXPERT_LLM env var)."""

import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from reasons_service.config import Settings


# --- Settings.llm_enabled property ---


class TestLlmEnabledProperty:
    """Test that the llm_enabled property parses EXPERT_LLM correctly."""

    def test_default_is_true(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EXPERT_LLM", None)
            s = Settings()
            assert s.llm_enabled is True

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "anything"])
    def test_truthy_values(self, value):
        with patch.dict(os.environ, {"EXPERT_LLM": value}):
            s = Settings()
            assert s.llm_enabled is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no"])
    def test_falsy_values(self, value):
        with patch.dict(os.environ, {"EXPERT_LLM": value}):
            s = Settings()
            assert s.llm_enabled is False


# --- Route presence in each mode (subprocess to get clean imports) ---


def _get_routes(llm_mode: str) -> list[str]:
    """Start a subprocess with EXPERT_LLM set, return route paths via OpenAPI schema."""
    env = {**os.environ, "EXPERT_LLM": llm_mode}
    env.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
    env.setdefault("DATABASE_URL_SYNC", "sqlite://")
    code = (
        "from reasons_service.app import app; "
        "from fastapi.openapi.utils import get_openapi; "
        "import json; "
        "schema = get_openapi(title='', version='', routes=app.routes); "
        "paths = sorted(schema.get('paths', {}).keys()); "
        "print(json.dumps(paths))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(result.stdout.strip())


_llm_routes_cache = {}


def _cached_routes(mode: str) -> list[str]:
    if mode not in _llm_routes_cache:
        _llm_routes_cache[mode] = _get_routes(mode)
    return _llm_routes_cache[mode]


CORE_ROUTES = [
    "/api/domains",
    "/api/domains/{domain_id}",
    "/api/domains/{domain_id}/ask",
    "/api/domains/{domain_id}/search",
    "/api/domains/{domain_id}/beliefs",
    "/api/domains/{domain_id}/beliefs/{node_id}",
    "/api/domains/{domain_id}/beliefs/{node_id}/explain",
    "/api/domains/{domain_id}/beliefs/{node_id}/what-if",
    "/api/domains/{domain_id}/entries",
    "/api/domains/{domain_id}/entries/{entry_id}",
    "/api/domains/{domain_id}/sources",
    "/api/domains/import-reasons",
    "/api/domains/{domain_id}/beliefs/propose",
    "/api/tenants",
    "/api/version",
    "/health",
    "/healthz",
    "/readyz",
]


class TestRoutePresence:
    """Verify core routes are registered in each mode."""

    @pytest.mark.parametrize("route", CORE_ROUTES)
    def test_route_in_llm_mode(self, route):
        routes = _cached_routes("true")
        assert route in routes

    @pytest.mark.parametrize("route", CORE_ROUTES)
    def test_route_in_no_llm_mode(self, route):
        routes = _cached_routes("false")
        assert route in routes


# -- Health endpoint reports mode --


def test_health_reports_llm_enabled():
    """Health endpoint includes llm field."""
    from fastapi.testclient import TestClient
    from reasons_service.app import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "llm" in body
    assert isinstance(body["llm"], bool)
