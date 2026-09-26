"""Tests for multi-tenancy: tenant isolation, RBAC, slug encoding, tenant CRUD, domain scoping."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from reasons_service.auth import _personal_tenant_slug
from reasons_service.rbac import Action, Role, UserInfo, has_permission


# ---------------------------------------------------------------------------
# Personal tenant slug encoding
# ---------------------------------------------------------------------------


class TestPersonalTenantSlug:
    """Injective slug encoding: no two emails produce the same slug."""

    def test_basic_email(self):
        assert _personal_tenant_slug("alice@example.com") == "personal-alice_at_example-com"

    def test_dots_in_local_part(self):
        assert _personal_tenant_slug("a.b.c@example.com") == "personal-a-b-c_at_example-com"

    def test_subdomain_email(self):
        assert _personal_tenant_slug("user@mail.corp.io") == "personal-user_at_mail-corp-io"

    def test_plus_addressing(self):
        slug = _personal_tenant_slug("user+tag@example.com")
        assert slug == "personal-user+tag_at_example-com"

    def test_injective_different_emails(self):
        """Two different emails must produce different slugs."""
        a = _personal_tenant_slug("alice@example.com")
        b = _personal_tenant_slug("bob@example.com")
        assert a != b

    def test_injective_dot_vs_at(self):
        """Ensure @ and . don't collide — a@b.c vs a.b@c produce different slugs."""
        a = _personal_tenant_slug("a@b.c")
        b = _personal_tenant_slug("a.b@c")
        assert a != b
        # a@b.c  -> personal-a_at_b-c
        # a.b@c  -> personal-a-b_at_c
        assert a == "personal-a_at_b-c"
        assert b == "personal-a-b_at_c"


# ---------------------------------------------------------------------------
# RBAC: tenant_admin role
# ---------------------------------------------------------------------------


class TestTenantAdminRole:
    """TENANT_ADMIN role has the right permissions."""

    def test_tenant_admin_can_read(self):
        assert has_permission(Role.TENANT_ADMIN, Action.READ)

    def test_tenant_admin_can_chat(self):
        assert has_permission(Role.TENANT_ADMIN, Action.CHAT)

    def test_tenant_admin_can_edit_beliefs(self):
        assert has_permission(Role.TENANT_ADMIN, Action.EDIT_BELIEFS)

    def test_tenant_admin_can_manage_sources(self):
        assert has_permission(Role.TENANT_ADMIN, Action.MANAGE_SOURCES)

    def test_tenant_admin_can_manage_domains(self):
        assert has_permission(Role.TENANT_ADMIN, Action.MANAGE_DOMAINS)

    def test_tenant_admin_can_propose_beliefs(self):
        assert has_permission(Role.TENANT_ADMIN, Action.PROPOSE_BELIEFS)

    def test_tenant_admin_can_review_proposals(self):
        assert has_permission(Role.TENANT_ADMIN, Action.REVIEW_PROPOSALS)

    def test_tenant_admin_cannot_admin(self):
        assert not has_permission(Role.TENANT_ADMIN, Action.ADMIN)

    def test_tenant_admin_is_between_admin_and_editor(self):
        """tenant_admin has manage_domains (editor doesn't) but not admin."""
        assert has_permission(Role.TENANT_ADMIN, Action.MANAGE_DOMAINS)
        assert not has_permission(Role.EDITOR, Action.MANAGE_DOMAINS)
        assert not has_permission(Role.TENANT_ADMIN, Action.ADMIN)
        assert has_permission(Role.ADMIN, Action.ADMIN)

    def test_role_enum_value(self):
        assert Role.TENANT_ADMIN == "tenant_admin"


# ---------------------------------------------------------------------------
# UserInfo tenant_id field
# ---------------------------------------------------------------------------


class TestUserInfoTenantId:
    """UserInfo dataclass carries tenant_id."""

    def test_tenant_id_default_none(self):
        user = UserInfo(identity="test@x.com", role=Role.READER)
        assert user.tenant_id is None

    def test_tenant_id_set(self):
        user = UserInfo(identity="test@x.com", role=Role.READER, tenant_id="personal-test_at_x-com")
        assert user.tenant_id == "personal-test_at_x-com"

    def test_frozen_tenant_id(self):
        user = UserInfo(identity="test@x.com", role=Role.READER, tenant_id="t1")
        with pytest.raises(AttributeError):
            user.tenant_id = "t2"


# ---------------------------------------------------------------------------
# Tenant CRUD API
# ---------------------------------------------------------------------------


def _make_tenant_app(user: UserInfo):
    """Create a test app with the tenants router and a fixed user."""
    from reasons_service.api.tenants import router as tenants_router
    from reasons_service.db.connection import get_session
    from reasons_service.auth import verify_auth

    app = FastAPI()
    app.include_router(tenants_router)

    class InjectUser(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = user
            return await call_next(request)

    app.add_middleware(InjectUser)
    app.dependency_overrides[verify_auth] = lambda: user
    return app


class TestTenantListAPI:
    """GET /api/tenants — list tenants the user belongs to."""

    def test_list_returns_user_tenants(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="alice@x.com", role=Role.EDITOR, tenant_id="t1")
        app = _make_tenant_app(user)

        mock_tenant = MagicMock()
        mock_tenant.id = "t1"
        mock_tenant.name = "t1"
        mock_tenant.display_name = "Tenant One"
        mock_tenant.type = "organization"
        mock_tenant.public = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_tenant]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.get("/api/tenants")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == "t1"
        assert items[0]["name"] == "t1"

    def test_list_empty_when_no_memberships(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="orphan@x.com", role=Role.READER)
        app = _make_tenant_app(user)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.get("/api/tenants")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


class TestTenantCreateAPI:
    """POST /api/tenants — create organization tenant."""

    def test_create_tenant_requires_editor_or_higher(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="reader@x.com", role=Role.READER)
        app = _make_tenant_app(user)

        mock_session = AsyncMock()
        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.post("/api/tenants", json={"name": "neworg"})
        assert resp.status_code == 403

    def test_create_tenant_success(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="editor@x.com", role=Role.EDITOR, tenant_id="personal-editor_at_x-com")
        app = _make_tenant_app(user)

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.tenants.fire_audit"):
            resp = client.post("/api/tenants", json={"name": "new-org", "display_name": "New Org"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "new-org"
        assert body["display_name"] == "New Org"
        assert body["type"] == "organization"
        assert mock_session.add.call_count == 2  # tenant + membership


class TestTenantGetAPI:
    """GET /api/tenants/{tenant_id} — get tenant details."""

    def test_member_can_view_tenant(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="alice@x.com", role=Role.EDITOR)
        app = _make_tenant_app(user)

        mock_tenant = MagicMock()
        mock_tenant.id = "t1"
        mock_tenant.name = "t1"
        mock_tenant.display_name = "Team One"
        mock_tenant.type = "organization"
        mock_tenant.public = False

        tenant_result = MagicMock()
        tenant_result.scalar_one_or_none.return_value = mock_tenant

        membership_result = MagicMock()
        membership_result.scalar_one_or_none.return_value = "editor"

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [tenant_result, membership_result]

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.get("/api/tenants/t1")
        assert resp.status_code == 200
        assert resp.json()["name"] == "t1"
        assert resp.json()["your_role"] == "editor"

    def test_non_member_cannot_view_private_tenant(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="outsider@x.com", role=Role.READER)
        app = _make_tenant_app(user)

        mock_tenant = MagicMock()
        mock_tenant.id = "t1"
        mock_tenant.public = False

        tenant_result = MagicMock()
        tenant_result.scalar_one_or_none.return_value = mock_tenant

        membership_result = MagicMock()
        membership_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [tenant_result, membership_result]

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.get("/api/tenants/t1")
        assert resp.status_code == 404

    def test_non_member_can_view_public_tenant(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="outsider@x.com", role=Role.READER)
        app = _make_tenant_app(user)

        mock_tenant = MagicMock()
        mock_tenant.id = "pub1"
        mock_tenant.name = "pub1"
        mock_tenant.display_name = "Public Org"
        mock_tenant.type = "organization"
        mock_tenant.public = True

        tenant_result = MagicMock()
        tenant_result.scalar_one_or_none.return_value = mock_tenant

        membership_result = MagicMock()
        membership_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [tenant_result, membership_result]

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.get("/api/tenants/pub1")
        assert resp.status_code == 200
        assert resp.json()["name"] == "pub1"
        assert resp.json()["your_role"] == "reader"


class TestTenantMemberAPI:
    """PUT/DELETE /api/tenants/{tenant_id}/members/{email} — member management."""

    def test_upsert_member_requires_tenant_admin(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="editor@x.com", role=Role.EDITOR)
        app = _make_tenant_app(user)

        membership_result = MagicMock()
        membership_result.scalar_one_or_none.return_value = "editor"

        mock_session = AsyncMock()
        mock_session.execute.return_value = membership_result

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.put("/api/tenants/t1/members/new@x.com", json={"role": "reader"})
        assert resp.status_code == 403

    def test_upsert_member_as_tenant_admin(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="admin@x.com", role=Role.EDITOR)
        app = _make_tenant_app(user)

        caller_membership = MagicMock()
        caller_membership.scalar_one_or_none.return_value = "tenant_admin"

        existing_member = MagicMock()
        existing_member.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [caller_membership, existing_member]
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.tenants.fire_audit"):
            resp = client.put("/api/tenants/t1/members/new@x.com", json={"role": "reader"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "new@x.com"
        assert resp.json()["role"] == "reader"

    def test_upsert_member_invalid_role(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="admin@x.com", role=Role.EDITOR)
        app = _make_tenant_app(user)

        caller_membership = MagicMock()
        caller_membership.scalar_one_or_none.return_value = "tenant_admin"

        mock_session = AsyncMock()
        mock_session.execute.return_value = caller_membership

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.put("/api/tenants/t1/members/new@x.com", json={"role": "superadmin"})
        assert resp.status_code == 400

    def test_remove_member_requires_tenant_admin(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="editor@x.com", role=Role.EDITOR)
        app = _make_tenant_app(user)

        membership_result = MagicMock()
        membership_result.scalar_one_or_none.return_value = "editor"

        mock_session = AsyncMock()
        mock_session.execute.return_value = membership_result

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        resp = client.delete("/api/tenants/t1/members/someone@x.com")
        assert resp.status_code == 403

    def test_global_admin_can_manage_any_tenant(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="superadmin@x.com", role=Role.ADMIN)
        app = _make_tenant_app(user)

        caller_membership = MagicMock()
        caller_membership.scalar_one_or_none.return_value = None

        existing_member = MagicMock()
        existing_member.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [caller_membership, existing_member]
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.tenants.fire_audit"):
            resp = client.put("/api/tenants/t1/members/new@x.com", json={"role": "editor"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Domain listing tenant scoping
# ---------------------------------------------------------------------------


def _make_domains_app(user: UserInfo):
    """Create test app with domains router and fixed user."""
    from reasons_service.api.domains import router as domains_router
    from reasons_service.db.connection import get_session
    from reasons_service.auth import verify_auth

    app = FastAPI()
    app.include_router(domains_router)

    class InjectUser(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = user
            return await call_next(request)

    app.add_middleware(InjectUser)
    app.dependency_overrides[verify_auth] = lambda: user
    return app


class TestDomainListScoping:
    """GET /api/domains — only returns domains the user can access."""

    def _mock_session_for_list(self, domains, *, is_admin=False):
        """Build a mock session that returns the given domains for list queries."""
        from reasons_service.db.connection import get_session

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = len(domains)

        mock_domains_result = MagicMock()
        mock_domains_result.scalars.return_value.all.return_value = domains

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [mock_count_result, mock_domains_result]

        return mock_session

    def _make_domain(self, name, tenant_id, public=False, members_only=False):
        d = MagicMock()
        d.id = uuid4()
        d.name = name
        d.description = f"Test domain {name}"
        d.config = {}
        d.public = public
        d.members_only = members_only
        d.allowed_tags = []
        d.created_at = MagicMock()
        d.created_at.isoformat.return_value = "2026-09-25T00:00:00"
        d.tenant_id = tenant_id
        return d

    def test_admin_sees_all_domains(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="admin@x.com", role=Role.ADMIN)
        app = _make_domains_app(user)

        d1 = self._make_domain("dom1", "t1")
        d2 = self._make_domain("dom2", "t2")
        mock_session = self._mock_session_for_list([d1, d2], is_admin=True)

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.domains._domain_counts", return_value=(0, 0, 0)):
            resp = client.get("/api/domains")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_regular_user_gets_filtered_query(self):
        """Non-admin users get a query that filters by tenant membership."""
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="alice@x.com", role=Role.EDITOR, tenant_id="t1")
        app = _make_domains_app(user)

        d1 = self._make_domain("my-domain", "t1")
        mock_session = self._mock_session_for_list([d1])

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.domains._domain_counts", return_value=(0, 0, 0)):
            resp = client.get("/api/domains")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "my-domain"


class TestDomainCreateScoping:
    """POST /api/domains — new domains get tenant_id."""

    def test_create_domain_sets_tenant_id(self):
        from reasons_service.db.connection import get_session
        from datetime import datetime, timezone
        user = UserInfo(identity="alice@x.com", role=Role.ADMIN, tenant_id="personal-alice_at_x-com")
        app = _make_domains_app(user)

        created_domains = []

        mock_session = AsyncMock()

        def capture_add(obj):
            if hasattr(obj, 'tenant_id') and hasattr(obj, 'name') and hasattr(obj, 'description'):
                created_domains.append(obj)
        mock_session.add = MagicMock(side_effect=capture_add)
        mock_session.commit = AsyncMock()

        async def fake_refresh(obj):
            if hasattr(obj, 'created_at') and obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            if hasattr(obj, 'id') and obj.id is None:
                obj.id = uuid4()
        mock_session.refresh = fake_refresh

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.domains.fire_audit"):
            resp = client.post("/api/domains", json={
                "name": "new-domain",
                "description": "test",
            })
        assert resp.status_code == 200
        assert len(created_domains) == 1
        assert created_domains[0].tenant_id == "personal-alice_at_x-com"


# ---------------------------------------------------------------------------
# Cross-tenant isolation: same domain name in different tenants
# ---------------------------------------------------------------------------


class TestCrossTenantIsolation:
    """Domains with the same name in different tenants don't leak."""

    def test_same_name_different_tenants_both_visible_to_admin(self):
        from reasons_service.db.connection import get_session
        user = UserInfo(identity="admin@x.com", role=Role.ADMIN)
        app = _make_domains_app(user)

        d1 = MagicMock()
        d1.id = uuid4()
        d1.name = "physics"
        d1.description = "Physics domain in tenant A"
        d1.config = {}
        d1.public = False
        d1.members_only = False
        d1.allowed_tags = []
        d1.created_at = MagicMock()
        d1.created_at.isoformat.return_value = "2026-09-25T00:00:00"
        d1.tenant_id = "tenant-a"

        d2 = MagicMock()
        d2.id = uuid4()
        d2.name = "physics"
        d2.description = "Physics domain in tenant B"
        d2.config = {}
        d2.public = False
        d2.members_only = False
        d2.allowed_tags = []
        d2.created_at = MagicMock()
        d2.created_at.isoformat.return_value = "2026-09-25T00:00:00"
        d2.tenant_id = "tenant-b"

        mock_count = MagicMock()
        mock_count.scalar.return_value = 2
        mock_domains = MagicMock()
        mock_domains.scalars.return_value.all.return_value = [d1, d2]

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [mock_count, mock_domains]

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)
        with patch("reasons_service.api.domains._domain_counts", return_value=(0, 0, 0)):
            resp = client.get("/api/domains")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        names = [i["name"] for i in items]
        assert names == ["physics", "physics"]
        assert items[0]["id"] != items[1]["id"]


# ---------------------------------------------------------------------------
# Auto-registration creates personal tenant
# ---------------------------------------------------------------------------


class TestAutoRegistration:
    """_auto_register creates personal tenant, user, and membership."""

    @pytest.mark.asyncio
    async def test_auto_register_creates_tenant_user_membership(self):
        from reasons_service.auth import _auto_register

        mock_session = AsyncMock()
        added_objects = []
        mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_user = MagicMock()
        mock_user.email = "new@example.com"
        mock_user.role = "reader"
        mock_user.tenant_id = "personal-new_at_example-com"
        mock_session.refresh = AsyncMock()

        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.public_registration = True
            result = await _auto_register("new@example.com", "New User", mock_session)

        assert len(added_objects) == 3
        tenant = added_objects[0]
        assert tenant.id == "personal-new_at_example-com"
        assert tenant.type == "personal"
        assert tenant.display_name == "new@example.com"

        user = added_objects[1]
        assert user.email == "new@example.com"
        assert user.role == "reader"
        assert user.tenant_id == "personal-new_at_example-com"

        membership = added_objects[2]
        assert membership.tenant_id == "personal-new_at_example-com"
        assert membership.user_email == "new@example.com"
        assert membership.role == "tenant_admin"

    @pytest.mark.asyncio
    async def test_auto_register_disabled_returns_none(self):
        from reasons_service.auth import _auto_register

        mock_session = AsyncMock()
        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.public_registration = False
            result = await _auto_register("new@example.com", "New User", mock_session)

        assert result is None
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_register_fk_order(self):
        """Tenant must be created before user (FK constraint)."""
        from reasons_service.auth import _auto_register

        add_order = []
        mock_session = AsyncMock()
        flush_count = [0]

        def track_add(obj):
            add_order.append((type(obj).__name__, flush_count[0]))
        mock_session.add = MagicMock(side_effect=track_add)

        original_flush = mock_session.flush
        async def track_flush():
            flush_count[0] += 1
        mock_session.flush = track_flush
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        with patch("reasons_service.auth.settings") as mock_settings:
            mock_settings.public_registration = True
            await _auto_register("order@test.com", "Order Test", mock_session)

        assert add_order[0][0] == "Tenant"
        assert add_order[1][0] == "User"
        assert add_order[2][0] == "TenantMember"
        assert add_order[0][1] < add_order[1][1]  # tenant flushed before user added


# ---------------------------------------------------------------------------
# _user_info includes tenant_id
# ---------------------------------------------------------------------------


class TestUserInfoFromDb:
    """_user_info builds UserInfo with tenant_id from DB user."""

    def test_user_info_includes_tenant_id(self):
        from reasons_service.auth import _user_info

        db_user = MagicMock()
        db_user.email = "test@x.com"
        db_user.role = Role.READER
        db_user.display_name = "Test"
        db_user.visible_tags = None
        db_user.writable_tags = None
        db_user.tenant_id = "personal-test_at_x-com"

        info = _user_info(db_user)
        assert info.tenant_id == "personal-test_at_x-com"
        assert info.identity == "test@x.com"

    def test_user_info_no_tenant_id(self):
        from reasons_service.auth import _user_info

        db_user = MagicMock()
        db_user.email = "old@x.com"
        db_user.role = Role.EDITOR
        db_user.display_name = None
        db_user.visible_tags = []
        db_user.writable_tags = []
        db_user.tenant_id = None

        info = _user_info(db_user)
        assert info.tenant_id is None
