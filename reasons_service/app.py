"""FastAPI application — API + web UI for reasons-service."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from reasons_service.api import domains, data, ask, public
from reasons_service.auth import router as auth_router, security, verify_auth, verify_auth_or_public, verify_auth_web, _LoginRedirect
from fastapi.security import HTTPAuthorizationCredentials
from reasons_service.config import settings
from reasons_service.db.connection import get_session, init_db
from reasons_service.db.models import Assessment, Entry, Domain, Source, entry_sources
from reasons_service.rbac import UserInfo
from reasons_service.mcp import mcp as mcp_server
from reasons_service.rms import api as rms_api



_mcp_http_app = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    """Create SQLite tables on startup (no-op for PostgreSQL)."""
    init_db()
    # Purge expired MCP access tokens
    import time
    from sqlalchemy import delete
    from reasons_service.db.models import McpAccessToken
    from reasons_service.db.connection import async_session
    async with async_session() as session:
        await session.execute(
            delete(McpAccessToken).where(McpAccessToken.expires_at <= int(time.time()))
        )
        await session.commit()
    async with mcp_server._session_manager.run():
        yield

app = FastAPI(title="Reasons Service", version="0.1.0", lifespan=lifespan)

# Session middleware for OAuth cookie sessions
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.middleware("http")
async def set_default_user(request: Request, call_next):
    """Ensure request.state.user always exists for templates."""
    request.state.user = None
    return await call_next(request)

# OAuth setup (optional — disabled when credentials not set)
oauth = None
if settings.google_client_id and settings.google_client_secret:
    if settings.secret_key == "dev-insecure-key":
        import warnings
        warnings.warn(
            "SECRET_KEY is set to the default insecure value. "
            "Set SECRET_KEY to a random string for production use.",
            stacklevel=1,
        )
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@app.exception_handler(_LoginRedirect)
async def login_redirect_handler(request: Request, exc: _LoginRedirect):
    if settings.hub_mode:
        return RedirectResponse(url="/")
    return RedirectResponse(url="/login")


def _open_fds() -> dict:
    """Return open file descriptor count and limit."""
    import os
    import resource
    try:
        count = len(os.listdir("/dev/fd"))
    except OSError:
        try:
            count = len(os.listdir(f"/proc/{os.getpid()}/fd"))
        except OSError:
            count = -1
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    return {"open": count, "limit_soft": soft, "limit_hard": hard}


@app.get("/health")
async def health():
    return {"status": "ok", "llm": settings.llm_enabled, "fds": _open_fds()}


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /domains/\n",
        media_type="text/plain",
    )


# Auth routes (login/callback/logout — disabled in hub mode)
if not settings.hub_mode:
    app.include_router(auth_router)


@app.get("/api/version", dependencies=[Depends(verify_auth)])
async def version():
    from reasons_service import __version__, _resolve_git_hash
    return {"version": __version__, "git_hash": _resolve_git_hash()}


# Public domain name resolution (must be before domains.router to avoid
# /api/domains/{domain_id} matching "resolve" as a domain_id)
@app.get("/api/domains/resolve")
async def resolve_domain_name(
    name: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    """Resolve a domain name to its ID. No auth needed for public domains."""
    result = await session.execute(
        select(Domain.id, Domain.public).where(Domain.name == name)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Domain '{name}' not found")
    if row.public:
        return {"id": str(row.id), "name": name, "public": True}
    # Private domain — require auth
    await verify_auth(request, credentials, session)
    return {"id": str(row.id), "name": name, "public": False}

# Public domain views (no auth — gated by domain.public flag)
app.include_router(public.landing_router)
app.include_router(public.router)

# API routes (protected by auth)
app.include_router(domains.router, dependencies=[Depends(verify_auth)])
app.include_router(data.router, dependencies=[Depends(verify_auth_or_public)])
app.include_router(data.tag_router, dependencies=[Depends(verify_auth)])

app.include_router(ask.router, dependencies=[Depends(verify_auth_or_public)])

# MCP OAuth discovery routes (RFC 9728 + RFC 8414)
# Must be on the parent app — MCP clients look for these at the domain root,
# not under the /mcp mount prefix.
if settings.google_client_id and settings.google_client_secret:
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
    from fastapi.responses import JSONResponse as _JSONResponse

    def _prm_response():
        issuer = settings.mcp_issuer_url
        return ProtectedResourceMetadata(
            resource=issuer,
            authorization_servers=[issuer],
        ).model_dump(mode="json", exclude_none=True)

    def _asm_response():
        issuer = settings.mcp_issuer_url.rstrip("/")
        return OAuthMetadata(
            issuer=issuer,
            authorization_endpoint=f"{issuer}/authorize",
            token_endpoint=f"{issuer}/token",
            registration_endpoint=f"{issuer}/register",
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
            code_challenge_methods_supported=["S256"],
        ).model_dump(mode="json", exclude_none=True)

    # Register at all paths clients may try (WWW-Authenticate hint, path-based, root)
    @app.get("/.well-known/oauth-protected-resource/mcp/mcp")
    async def mcp_prm_full():
        return _prm_response()

    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def mcp_prm_short():
        return _prm_response()

    @app.get("/.well-known/oauth-protected-resource")
    async def mcp_prm_root():
        return _prm_response()

    @app.get("/.well-known/oauth-authorization-server/mcp")
    async def mcp_asm_path():
        return _asm_response()

    @app.get("/.well-known/oauth-authorization-server")
    async def mcp_asm_root():
        return _asm_response()

# MCP server (streamable HTTP at /mcp)
app.mount("/mcp", _mcp_http_app)


@app.middleware("http")
async def mcp_trailing_slash(request: Request, call_next):
    """Rewrite /mcp to /mcp/ internally to avoid Starlette's 307 redirect."""
    if request.url.path == "/mcp":
        request.scope["path"] = "/mcp/"
    return await call_next(request)

# Static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# Templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["llm_enabled"] = settings.llm_enabled
templates.env.globals["hub_mode"] = settings.hub_mode


# --- Web UI Routes ---


@app.get("/guide", response_class=HTMLResponse)
async def guide(request: Request):
    """Getting started guide — connecting Claude Code and Claude Desktop."""
    return templates.TemplateResponse(request, "guide.html", {
        "mcp_url": settings.mcp_issuer_url,
    })


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    """Public landing page — lists public domains, links to login."""
    result = await session.execute(
        select(Domain).where(Domain.public == True).order_by(Domain.name)
    )
    domain_list = result.scalars().all()
    public_domains = []
    for d in domain_list:
        belief_count = await asyncio.to_thread(rms_api.count_beliefs, d.id, "IN")
        public_domains.append({
            "name": d.name,
            "description": d.description,
            "belief_count": belief_count,
        })
    return templates.TemplateResponse(request, "home.html", {
        "public_domains": public_domains,
    })


if not settings.hub_mode:
    @app.get("/domains", response_class=HTMLResponse)
    async def domains_list(request: Request, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
        """Authenticated domains list page."""
        result = await session.execute(select(Domain).order_by(Domain.created_at.desc()))
        all_domains = result.scalars().all()

        domains_with_stats = []
        for d in all_domains:
            source_count = await session.scalar(
                select(func.count()).select_from(Source).where(Source.domain_id == d.id)
            )
            entry_count = await session.scalar(
                select(func.count()).select_from(Entry).where(Entry.domain_id == d.id)
            )
            belief_count = await asyncio.to_thread(rms_api.count_beliefs, d.id, "IN")
            domains_with_stats.append({
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "source_count": source_count or 0,
                "entry_count": entry_count or 0,
                "belief_count": belief_count or 0,
            })

        return templates.TemplateResponse(request, "domains/list.html", {
            "domains": domains_with_stats,
        })

    @app.get("/domains/new", response_class=HTMLResponse)
    async def new_domain_form(request: Request, _user: UserInfo = Depends(verify_auth_web)):
        return templates.TemplateResponse(request, "domains/create.html")

    @app.post("/domains/new")
    async def create_domain_form(
        request: Request,
        name: str = Form(...),
        description: str = Form(...),
        _user: UserInfo = Depends(verify_auth_web),
        session: AsyncSession = Depends(get_session),
    ):
        domain_obj = Domain(name=name, description=description)
        session.add(domain_obj)
        await session.commit()
        await session.refresh(domain_obj)
        return RedirectResponse(f"/domains/{domain_obj.id}", status_code=303)


@app.get("/domains/{domain_id}", response_class=HTMLResponse)
async def domain_detail(
    request: Request,
    domain_id: UUID,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain_obj = result.scalar_one_or_none()
    if not domain_obj:
        return HTMLResponse("Domain not found", status_code=404)

    stats = {
        "sources": await session.scalar(
            select(func.count()).select_from(Source).where(Source.domain_id == domain_id)
        ) or 0,
        "entries": await session.scalar(
            select(func.count()).select_from(Entry).where(Entry.domain_id == domain_id)
        ) or 0,
        "beliefs": await asyncio.to_thread(rms_api.count_beliefs, domain_id, "IN"),
        "nogoods": await asyncio.to_thread(rms_api.count_nogoods, domain_id),
        "assessments": await session.scalar(
            select(func.count()).select_from(Assessment).where(Assessment.domain_id == domain_id)
        ) or 0,
    }

    entry_result = await session.execute(
        select(Entry.id, Entry.topic, Entry.title, Entry.created_at)
        .where(Entry.domain_id == domain_id)
        .order_by(Entry.created_at.desc())
        .limit(10)
    )
    entries = [dict(r._mapping) for r in entry_result.all()]
    for e in entries:
        e["created_at"] = e["created_at"].isoformat() if e["created_at"] else ""

    return templates.TemplateResponse(request, "domains/detail.html", {
        "domain": {"id": domain_id, "name": domain_obj.name, "description": domain_obj.description},
        "stats": stats,
        "entries": entries,
    })


@app.get("/domains/{domain_id}/sources/{slug}/view", response_class=HTMLResponse)
async def source_content_view(
    request: Request,
    domain_id: UUID,
    slug: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render a source document's original content."""
    domain_obj = (await session.execute(
        select(Domain).where(Domain.id == domain_id)
    )).scalar_one_or_none()
    if not domain_obj:
        return HTMLResponse("Domain not found", status_code=404)
    source = (await session.execute(
        select(Source).where(Source.domain_id == domain_id, Source.slug == slug)
    )).scalar_one_or_none()
    if not source:
        return HTMLResponse(f"Source not found: {slug}", status_code=404)
    return templates.TemplateResponse(request, "entries/view.html", {
        "domain": {"id": domain_id, "name": domain_obj.name},
        "entry": {"id": slug, "title": slug, "topic": slug},
        "content_json": json.dumps(source.content),
        "linked_sources": [],
    })


@app.get("/domains/{domain_id}/source/{path:path}", response_class=HTMLResponse)
async def source_view(
    request: Request,
    domain_id: UUID,
    path: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render a source document by its path (e.g. entries/2026/04/23/scan-ftl-reasons.md).

    Looks up the entry by matching the topic (filename stem) against entries in the domain.
    """
    domain_obj = (await session.execute(
        select(Domain).where(Domain.id == domain_id)
    )).scalar_one_or_none()
    if not domain_obj:
        return HTMLResponse("Domain not found", status_code=404)

    topic = Path(path).stem

    from sqlalchemy.orm import selectinload
    entry = (await session.execute(
        select(Entry).options(selectinload(Entry.sources))
        .where(Entry.domain_id == domain_id, Entry.topic == topic).limit(1)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse(f"Source not found: {path}", status_code=404)

    return templates.TemplateResponse(request, "entries/view.html", {
        "domain": {"id": domain_id, "name": domain_obj.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
        "linked_sources": [{"slug": s.slug} for s in entry.sources],
    })


@app.get("/domains/{domain_id}/entries/{entry_id}/view", response_class=HTMLResponse)
async def entry_view(
    request: Request,
    domain_id: UUID,
    entry_id: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render an entry's markdown content in a simple viewer."""
    domain_obj = (await session.execute(
        select(Domain).where(Domain.id == domain_id)
    )).scalar_one_or_none()
    if not domain_obj:
        return HTMLResponse("Domain not found", status_code=404)

    from sqlalchemy.orm import selectinload
    entry = (await session.execute(
        select(Entry).options(selectinload(Entry.sources))
        .where(Entry.domain_id == domain_id, Entry.id == entry_id)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse("Entry not found", status_code=404)

    return templates.TemplateResponse(request, "entries/view.html", {
        "domain": {"id": domain_id, "name": domain_obj.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
        "linked_sources": [{"slug": s.slug} for s in entry.sources],
    })


@app.get("/domains/{domain_id}/entries/{entry_id}/report", response_class=HTMLResponse)
async def entry_report(
    request: Request,
    domain_id: UUID,
    entry_id: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render an entry as an interactive report with Explain/What-if buttons on belief references."""
    domain_obj = (await session.execute(
        select(Domain).where(Domain.id == domain_id)
    )).scalar_one_or_none()
    if not domain_obj:
        return HTMLResponse("Domain not found", status_code=404)

    entry = (await session.execute(
        select(Entry).where(Entry.domain_id == domain_id, Entry.id == entry_id)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse("Entry not found", status_code=404)

    return templates.TemplateResponse(request, "reports/view.html", {
        "domain": {"id": domain_id, "name": domain_obj.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
    })


def main():
    """Entry point for the reasons-service command."""
    uvicorn.run("reasons_service.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
