"""Test that MCP tools forward user identity to the REST API."""

from unittest.mock import MagicMock, patch

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.provider import AccessToken

from reasons_service.mcp import _headers


def test_headers_uses_mcp_access_token_when_present():
    token = AccessToken(
        token="mcp-user-token-abc",
        client_id="test-client",
        scopes=[],
        subject="alice@example.com",
    )
    user = MagicMock()
    user.access_token = token
    ctx_token = auth_context_var.set(user)
    try:
        result = _headers()
    finally:
        auth_context_var.reset(ctx_token)

    assert result == {"Authorization": "Bearer mcp-user-token-abc"}


def test_headers_falls_back_to_api_key_when_no_mcp_context():
    with patch("reasons_service.mcp.settings") as mock_settings:
        mock_settings.api_key = "static-key-123"
        result = _headers()
    assert result == {"Authorization": "Bearer static-key-123"}


def test_headers_returns_empty_when_no_auth():
    with patch("reasons_service.mcp.settings") as mock_settings:
        mock_settings.api_key = ""
        result = _headers()
    assert result == {}
