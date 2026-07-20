"""Tests for authentication and RBAC."""

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from reasons_service.auth import verify_auth, verify_auth_or_public, verify_auth_web, _LoginRedirect
from reasons_service.rbac import Action, Role, UserInfo, has_permission, require_action


# --- Fixtures ---


def _make_app(auth_dep=verify_auth):
    """Create a test app with auth dependency and a protected route."""
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.exception_handler(_LoginRedirect)
    async def login_redirect_handler(request, exc):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login")

    @app.get("/protected")
    async def protected(user: UserInfo = Depends(auth_dep)):
        return {"identity": user.identity, "role": user.role}

    @app.get("/web-protected")
    async def web_protected(user: UserInfo = Depends(verify_auth_web)):
        return {"identity": user.identity, "role": user.role}

    @app.get("/login")
    async def login():
        return JSONResponse({"page": "login"})

    return app


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
def client(app):
    return TestClient(app)


# --- Dev mode (no GOOGLE_CLIENT_ID) ---


class TestDevMode:
    """When GOOGLE_CLIENT_ID is unset, anonymous access is allowed."""

    def test_anonymous_access_allowed(self, client):
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.google_client_id = ""
            mock_settings.api_key = ""
            resp = client.get("/protected")
        assert resp.status_code == 200
        body = resp.json()
        assert body["identity"] == "dev"
        assert body["role"] == "admin"

    def test_dev_mode_user_is_admin(self, client):
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.google_client_id = ""
            mock_settings.api_key = ""
            resp = client.get("/protected")
        assert resp.json()["role"] == "admin"


# --- Bearer token ---


class TestBearerToken:
    """Bearer token authentication for API access."""

    def test_valid_bearer_token(self, client):
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = "test-api-key-12345"
            mock_settings.google_client_id = "set"
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer test-api-key-12345"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["identity"] == "api"
        assert body["role"] == "admin"

    def test_invalid_bearer_token(self, client):
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            mock_settings.google_client_id = "set"
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert resp.status_code == 401

    def test_bearer_token_ignored_when_api_key_unset(self, client):
        """When EXPERT_SERVICE_API_KEY is empty, bearer tokens are ignored."""
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer anything"},
            )
        assert resp.status_code == 401

    def test_bearer_token_empty_string_rejected(self, client):
        """Empty bearer token should not match empty api_key."""
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer "},
            )
        assert resp.status_code == 401


# --- OAuth session ---


class TestNoSession:
    """When OAuth is configured but no session cookie is present."""

    def test_no_session_returns_401(self, client):
        """Without a session cookie, should get 401 when OAuth is configured."""
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/protected")
        assert resp.status_code == 401

    def test_no_session_no_bearer_returns_401(self, client):
        """Neither session nor bearer token — 401."""
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = "some-key"
            mock_settings.google_client_id = "set"
            resp = client.get("/protected")
        assert resp.status_code == 401


# --- Unauthenticated ---


class TestUnauthenticated:
    """When OAuth is configured and no credentials provided."""

    def test_no_credentials_returns_401(self, client):
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/protected")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"

    def test_no_credentials_does_not_leak_config(self, client):
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            mock_settings.google_client_id = "client-id-value"
            resp = client.get("/protected")
        body = resp.json()
        assert "secret-key" not in str(body)
        assert "client-id-value" not in str(body)


# --- Web auth redirect ---


class TestWebAuthRedirect:
    """verify_auth_web redirects to /login instead of returning 401."""

    def test_unauthenticated_web_redirects_to_login(self):
        app = _make_app()
        client = TestClient(app, follow_redirects=False)
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/web-protected")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/login"

    def test_authenticated_web_returns_user(self):
        app = _make_app()
        client = TestClient(app)
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = "key123"
            mock_settings.google_client_id = "set"
            resp = client.get(
                "/web-protected",
                headers={"Authorization": "Bearer key123"},
            )
        assert resp.status_code == 200
        assert resp.json()["identity"] == "api"

    def test_unauthenticated_web_gets_redirected(self):
        """401 (no credentials) should redirect to /login."""
        app = _make_app()
        client = TestClient(app, follow_redirects=False)

        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/web-protected")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/login"


# --- Login/logout routes ---


class TestLoginRoutes:
    """OAuth login/callback/logout route behavior."""

    def test_login_returns_501_when_oauth_not_configured(self):
        from reasons_service.auth import router as auth_router
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test")
        app.include_router(auth_router)
        client = TestClient(app)

        with patch("reasons_service.app.oauth", None):
            resp = client.get("/login")
        assert resp.status_code == 501
        assert "OAuth not configured" in resp.text

    def test_logout_clears_session(self):
        from reasons_service.auth import router as auth_router
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test")
        app.include_router(auth_router)
        client = TestClient(app, follow_redirects=False)

        resp = client.get("/logout")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/login"


# --- RBAC permission checks ---


class TestRBAC:
    """Role-based access control permission matrix."""

    def test_admin_has_all_permissions(self):
        for action in Action:
            assert has_permission(Role.ADMIN, action) is True

    def test_editor_permissions(self):
        assert has_permission(Role.EDITOR, Action.READ) is True
        assert has_permission(Role.EDITOR, Action.CHAT) is True
        assert has_permission(Role.EDITOR, Action.EDIT_BELIEFS) is True
        assert has_permission(Role.EDITOR, Action.MANAGE_SOURCES) is True
        assert has_permission(Role.EDITOR, Action.MANAGE_DOMAINS) is False
        assert has_permission(Role.EDITOR, Action.ADMIN) is False

    def test_reader_permissions(self):
        assert has_permission(Role.READER, Action.READ) is True
        assert has_permission(Role.READER, Action.CHAT) is True
        assert has_permission(Role.READER, Action.EDIT_BELIEFS) is False
        assert has_permission(Role.READER, Action.MANAGE_SOURCES) is False
        assert has_permission(Role.READER, Action.MANAGE_DOMAINS) is False
        assert has_permission(Role.READER, Action.ADMIN) is False

    def test_unknown_role_has_no_permissions(self):
        for action in Action:
            assert has_permission("unknown", action) is False

    def test_require_action_allows_permitted(self):
        from fastapi import Request as FastAPIRequest
        from starlette.middleware.base import BaseHTTPMiddleware

        app = FastAPI()

        @app.get("/test", dependencies=[Depends(require_action(Action.READ))])
        async def test_route(request: FastAPIRequest):
            return {"ok": True}

        class InjectUser(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user = UserInfo(identity="test", role=Role.EDITOR)
                return await call_next(request)

        app.add_middleware(InjectUser)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_require_action_blocks_unpermitted(self):
        app = FastAPI()

        @app.get("/admin-only", dependencies=[Depends(require_action(Action.ADMIN))])
        async def admin_route(request: Request):
            return {"ok": True}

        from starlette.middleware.base import BaseHTTPMiddleware

        class InjectReader(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user = UserInfo(identity="test", role=Role.READER)
                return await call_next(request)

        app.add_middleware(InjectReader)
        client = TestClient(app)
        resp = client.get("/admin-only")
        assert resp.status_code == 403
        assert "lacks" in resp.json()["detail"]


# --- UserInfo ---


class TestUserInfo:
    """UserInfo dataclass behavior."""

    def test_userinfo_is_frozen(self):
        user = UserInfo(identity="test@example.com", role=Role.ADMIN)
        with pytest.raises(AttributeError):
            user.identity = "changed"

    def test_userinfo_optional_display_name(self):
        user = UserInfo(identity="test@example.com", role=Role.READER)
        assert user.display_name is None

        user2 = UserInfo(identity="test@example.com", role=Role.READER, display_name="Test")
        assert user2.display_name == "Test"

    def test_role_enum_compares_with_string(self):
        """StrEnum roles should compare equal to plain strings."""
        assert Role.ADMIN == "admin"
        assert Role.EDITOR == "editor"
        assert Role.READER == "reader"


# --- Public domain access ---


class TestPublicProjectAccess:
    """verify_auth_or_public allows unauthenticated access to public projects."""

    @staticmethod
    def _make_public_app(public_value):
        from unittest.mock import AsyncMock, MagicMock
        from reasons_service.db.connection import get_session

        mock_row = MagicMock()
        mock_row.public = public_value

        mock_result = MagicMock()
        mock_result.first.return_value = mock_row if public_value is not None else None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.dependency_overrides[get_session] = lambda: mock_session

        @app.get("/api/domains/{domain_id}/data")
        async def project_data(domain_id: str, user: UserInfo = Depends(verify_auth_or_public)):
            return {"identity": user.identity, "role": user.role}

        return app

    def test_public_project_allows_anonymous(self):
        app = self._make_public_app(True)
        client = TestClient(app)
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/api/domains/00000000-0000-0000-0000-000000000001/data")
        assert resp.status_code == 200
        body = resp.json()
        assert body["identity"] == "public"
        assert body["role"] == "reader"

    def test_private_project_requires_auth(self):
        app = self._make_public_app(False)
        client = TestClient(app)
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/api/domains/00000000-0000-0000-0000-000000000001/data")
        assert resp.status_code == 401

    def test_nonexistent_project_requires_auth(self):
        app = self._make_public_app(None)
        client = TestClient(app)
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.google_client_id = "set"
            resp = client.get("/api/domains/00000000-0000-0000-0000-000000000099/data")
        assert resp.status_code == 401

    def test_public_project_with_api_key_preserves_identity(self):
        """Authenticated users on public projects keep their real identity."""
        app = self._make_public_app(True)
        client = TestClient(app)
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.api_key = "test-key"
            mock_settings.google_client_id = "set"
            resp = client.get(
                "/api/domains/00000000-0000-0000-0000-000000000001/data",
                headers={"Authorization": "Bearer test-key"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["identity"] == "api"
        assert body["role"] == "admin"
