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
    """Start a subprocess with EXPERT_LLM set, import app, return route paths."""
    env = {**os.environ, "EXPERT_LLM": llm_mode}
    code = (
        "from reasons_service.app import app; "
        "import json; "
        "paths = sorted(set(r.path for r in app.routes if hasattr(r, 'path'))); "
        "print(json.dumps(paths))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(result.stdout.strip())


class TestRoutePresence:
    """Verify which routes are registered in each mode."""

    @pytest.fixture(scope="class")
    def llm_routes(self):
        return _get_routes("true")

    @pytest.fixture(scope="class")
    def no_llm_routes(self):
        return _get_routes("false")

    # -- LLM-only routes present in LLM mode --

    def test_chat_route_in_llm_mode(self, llm_routes):
        assert "/api/projects/{project_id}/chat" in llm_routes

    def test_meta_chat_route_in_llm_mode(self, llm_routes):
        assert "/api/meta/chat" in llm_routes

    def test_pipeline_route_in_llm_mode(self, llm_routes):
        assert "/api/projects/{project_id}/ingest" in llm_routes

    def test_propose_route_in_llm_mode(self, llm_routes):
        assert "/api/projects/{project_id}/beliefs/propose" in llm_routes

    def test_chat_page_in_llm_mode(self, llm_routes):
        assert "/projects/{project_id}/chat" in llm_routes

    def test_meta_chat_page_in_llm_mode(self, llm_routes):
        assert "/meta/chat" in llm_routes

    def test_ingest_page_in_llm_mode(self, llm_routes):
        assert "/projects/{project_id}/ingest" in llm_routes

    # -- LLM-only routes absent in no-LLM mode --

    def test_chat_route_absent_no_llm(self, no_llm_routes):
        assert "/api/projects/{project_id}/chat" not in no_llm_routes

    def test_meta_chat_route_absent_no_llm(self, no_llm_routes):
        assert "/api/meta/chat" not in no_llm_routes

    def test_pipeline_route_absent_no_llm(self, no_llm_routes):
        assert "/api/projects/{project_id}/ingest" not in no_llm_routes

    def test_propose_route_absent_no_llm(self, no_llm_routes):
        assert "/api/projects/{project_id}/beliefs/propose" not in no_llm_routes

    def test_chat_page_absent_no_llm(self, no_llm_routes):
        assert "/projects/{project_id}/chat" not in no_llm_routes

    def test_meta_chat_page_absent_no_llm(self, no_llm_routes):
        assert "/meta/chat" not in no_llm_routes

    def test_ingest_page_absent_no_llm(self, no_llm_routes):
        assert "/projects/{project_id}/ingest" not in no_llm_routes

    # -- Data routes present in BOTH modes --

    @pytest.mark.parametrize("route", [
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/ask",
        "/api/projects/{project_id}/search",
        "/api/projects/{project_id}/beliefs",
        "/api/projects/{project_id}/beliefs/{node_id}",
        "/api/projects/{project_id}/beliefs/{node_id}/explain",
        "/api/projects/{project_id}/beliefs/{node_id}/what-if",
        "/api/projects/{project_id}/entries",
        "/api/projects/{project_id}/entries/{entry_id}",
        "/api/projects/{project_id}/sources",
        "/api/projects/import-reasons",
        "/health",
    ])
    def test_data_route_in_llm_mode(self, llm_routes, route):
        assert route in llm_routes

    @pytest.mark.parametrize("route", [
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/ask",
        "/api/projects/{project_id}/search",
        "/api/projects/{project_id}/beliefs",
        "/api/projects/{project_id}/beliefs/{node_id}",
        "/api/projects/{project_id}/beliefs/{node_id}/explain",
        "/api/projects/{project_id}/beliefs/{node_id}/what-if",
        "/api/projects/{project_id}/entries",
        "/api/projects/{project_id}/entries/{entry_id}",
        "/api/projects/{project_id}/sources",
        "/api/projects/import-reasons",
        "/health",
    ])
    def test_data_route_in_no_llm_mode(self, no_llm_routes, route):
        assert route in no_llm_routes


# -- No LLM deps loaded in no-LLM mode --


def test_no_llm_deps_in_no_llm_mode():
    """Verify langchain/langgraph are not imported when EXPERT_LLM=false."""
    env = {**os.environ, "EXPERT_LLM": "false"}
    code = (
        "from reasons_service.app import app; "
        "import sys; "
        "llm = [m for m in sys.modules if 'langchain' in m or 'langgraph' in m]; "
        "print(len(llm))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert result.stdout.strip() == "0", (
        f"LLM modules loaded in no-LLM mode: {result.stdout}"
    )


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
