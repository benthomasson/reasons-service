"""FastAPI application — API + web UI for reasons-service."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from reasons_service.api import projects, data, ask, public
from reasons_service.auth import router as auth_router, security, verify_auth, verify_auth_or_public, verify_auth_web, _LoginRedirect
from fastapi.security import HTTPAuthorizationCredentials
from reasons_service.config import settings
from reasons_service.db.connection import get_session, init_db
from reasons_service.db.models import Assessment, Entry, Project, Source, entry_sources
from reasons_service.rbac import UserInfo
from reasons_service.mcp import mcp as mcp_server
from reasons_service.rms import api as rms_api

# LLM-dependent modules — only imported when LLM mode is enabled.
# In no-LLM mode, clients bring their own LLM and use the data endpoints directly.
if settings.llm_enabled:
    from reasons_service.api import pipeline, chat, meta_chat
    from reasons_service.chat.meta_agent import invalidate_meta_cache
else:
    def invalidate_meta_cache(): pass


_mcp_http_app = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    """Create SQLite tables on startup (no-op for PostgreSQL)."""
    init_db()
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
        "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /projects/\n",
        media_type="text/plain",
    )


# Auth routes (login/callback/logout — disabled in hub mode)
if not settings.hub_mode:
    app.include_router(auth_router)


@app.get("/api/version", dependencies=[Depends(verify_auth)])
async def version():
    from reasons_service import __version__, _resolve_git_hash
    return {"version": __version__, "git_hash": _resolve_git_hash()}


# Public project name resolution (must be before projects.router to avoid
# /api/projects/{project_id} matching "resolve" as a project_id)
@app.get("/api/projects/resolve")
async def resolve_project_name(
    name: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    """Resolve a project name to its ID. No auth needed for public projects."""
    result = await session.execute(
        select(Project.id, Project.public).where(Project.name == name)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    if row.public:
        return {"id": str(row.id), "name": name, "public": True}
    # Private project — require auth
    await verify_auth(request, credentials, session)
    return {"id": str(row.id), "name": name, "public": False}

# Public project views (no auth — gated by project.public flag)
app.include_router(public.landing_router)
app.include_router(public.router)

# API routes (protected by auth)
app.include_router(projects.router, dependencies=[Depends(verify_auth)])
app.include_router(data.router, dependencies=[Depends(verify_auth_or_public)])
app.include_router(data.tag_router, dependencies=[Depends(verify_auth)])

if settings.llm_enabled:
    # LLM mode: chat.router provides /chat (streaming) and /ask (LLM-synthesized)
    app.include_router(chat.router, dependencies=[Depends(verify_auth_or_public)])
    app.include_router(meta_chat.router, dependencies=[Depends(verify_auth)])
    app.include_router(pipeline.router, dependencies=[Depends(verify_auth)])

# Always register: FTS-only /ask (shadowed by chat.router's /ask in LLM mode)
app.include_router(ask.router, dependencies=[Depends(verify_auth_or_public)])

# MCP OAuth discovery routes (RFC 9728 + RFC 8414)
# Must be on the parent app — MCP clients look for these at the domain root,
# not under the /mcp mount prefix.
if settings.google_client_id and settings.google_client_secret:
    from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
    from fastapi.responses import JSONResponse as _JSONResponse

    def _prm_response():
        issuer = settings.mcp_issuer_url
        resource = f"{issuer}/mcp"
        return ProtectedResourceMetadata(
            resource=resource,
            authorization_servers=[issuer],
        ).model_dump(mode="json")

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
        ).model_dump(mode="json")

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

# Templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["llm_enabled"] = settings.llm_enabled
templates.env.globals["hub_mode"] = settings.hub_mode


# --- Web UI Routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    """Public landing page — lists public experts, links to login."""
    result = await session.execute(
        select(Project).where(Project.public == True).order_by(Project.name)
    )
    projects = result.scalars().all()
    experts = []
    for p in projects:
        belief_count = await asyncio.to_thread(rms_api.count_beliefs, p.id, "IN")
        experts.append({
            "name": p.name,
            "domain": p.domain,
            "belief_count": belief_count,
        })
    return templates.TemplateResponse(request, "home.html", {
        "experts": experts,
    })


if not settings.hub_mode:
    @app.get("/projects", response_class=HTMLResponse)
    async def projects_list(request: Request, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
        """Authenticated projects list page."""
        result = await session.execute(select(Project).order_by(Project.created_at.desc()))
        project_list = result.scalars().all()

        projects_with_stats = []
        for p in project_list:
            source_count = await session.scalar(
                select(func.count()).select_from(Source).where(Source.project_id == p.id)
            )
            entry_count = await session.scalar(
                select(func.count()).select_from(Entry).where(Entry.project_id == p.id)
            )
            belief_count = await asyncio.to_thread(rms_api.count_beliefs, p.id, "IN")
            projects_with_stats.append({
                "id": p.id,
                "name": p.name,
                "domain": p.domain,
                "source_count": source_count or 0,
                "entry_count": entry_count or 0,
                "belief_count": belief_count or 0,
            })

        return templates.TemplateResponse(request, "projects/list.html", {
            "projects": projects_with_stats,
        })

    @app.get("/projects/new", response_class=HTMLResponse)
    async def new_project_form(request: Request, _user: UserInfo = Depends(verify_auth_web)):
        return templates.TemplateResponse(request, "projects/create.html")

    @app.post("/projects/new")
    async def create_project_form(
        request: Request,
        name: str = Form(...),
        domain: str = Form(...),
        _user: UserInfo = Depends(verify_auth_web),
        session: AsyncSession = Depends(get_session),
    ):
        project = Project(name=name, domain=domain)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        invalidate_meta_cache()
        return RedirectResponse(f"/projects/{project.id}", status_code=303)


if settings.llm_enabled:
    @app.get("/meta/chat", response_class=HTMLResponse)
    async def meta_chat_page(request: Request, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
        """Meta-expert chat page — routes questions across all domain experts."""
        result = await session.execute(select(Project).order_by(Project.name))
        project_list = result.scalars().all()
        experts = [
            {"name": p.name, "domain": p.domain, "id": str(p.id)}
            for p in project_list
            if p.name != "meta-expert"
        ]
        return templates.TemplateResponse(request, "chat/meta_chat.html", {
            "experts": experts,
        })


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request,
    project_id: UUID,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    stats = {
        "sources": await session.scalar(
            select(func.count()).select_from(Source).where(Source.project_id == project_id)
        ) or 0,
        "entries": await session.scalar(
            select(func.count()).select_from(Entry).where(Entry.project_id == project_id)
        ) or 0,
        "beliefs": await asyncio.to_thread(rms_api.count_beliefs, project_id, "IN"),
        "nogoods": await asyncio.to_thread(rms_api.count_nogoods, project_id),
        "assessments": await session.scalar(
            select(func.count()).select_from(Assessment).where(Assessment.project_id == project_id)
        ) or 0,
    }

    entry_result = await session.execute(
        select(Entry.id, Entry.topic, Entry.title, Entry.created_at)
        .where(Entry.project_id == project_id)
        .order_by(Entry.created_at.desc())
        .limit(10)
    )
    entries = [dict(r._mapping) for r in entry_result.all()]
    for e in entries:
        e["created_at"] = e["created_at"].isoformat() if e["created_at"] else ""

    return templates.TemplateResponse(request, "projects/detail.html", {
        "project": {"id": project_id, "name": project.name, "domain": project.domain},
        "stats": stats,
        "entries": entries,
    })


if settings.llm_enabled:
    @app.get("/projects/{project_id}/chat", response_class=HTMLResponse)
    async def chat_page(request: Request, project_id: UUID, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return HTMLResponse("Project not found", status_code=404)
        # Redirect meta-expert project chat to the dedicated meta-expert UI
        if project.name == "meta-expert":
            return RedirectResponse("/meta/chat", status_code=303)
        return templates.TemplateResponse(request, "chat/chat.html", {
            "project": {"id": project_id, "name": project.name, "domain": project.domain},
        })


@app.get("/projects/{project_id}/sources/{slug}/view", response_class=HTMLResponse)
async def source_content_view(
    request: Request,
    project_id: UUID,
    slug: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render a source document's original content."""
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)
    source = (await session.execute(
        select(Source).where(Source.project_id == project_id, Source.slug == slug)
    )).scalar_one_or_none()
    if not source:
        return HTMLResponse(f"Source not found: {slug}", status_code=404)
    return templates.TemplateResponse(request, "entries/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": slug, "title": slug, "topic": slug},
        "content_json": json.dumps(source.content),
        "linked_sources": [],
    })


@app.get("/projects/{project_id}/source/{path:path}", response_class=HTMLResponse)
async def source_view(
    request: Request,
    project_id: UUID,
    path: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render a source document by its path (e.g. entries/2026/04/23/scan-ftl-reasons.md).

    Looks up the entry by matching the topic (filename stem) against entries in the project.
    """
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    # Extract topic from path: "entries/2026/04/23/scan-ftl-reasons.md" → "scan-ftl-reasons"
    topic = Path(path).stem

    from sqlalchemy.orm import selectinload
    entry = (await session.execute(
        select(Entry).options(selectinload(Entry.sources))
        .where(Entry.project_id == project_id, Entry.topic == topic).limit(1)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse(f"Source not found: {path}", status_code=404)

    return templates.TemplateResponse(request, "entries/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
        "linked_sources": [{"slug": s.slug} for s in entry.sources],
    })


@app.get("/projects/{project_id}/entries/{entry_id}/view", response_class=HTMLResponse)
async def entry_view(
    request: Request,
    project_id: UUID,
    entry_id: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render an entry's markdown content in a simple viewer."""
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    from sqlalchemy.orm import selectinload
    entry = (await session.execute(
        select(Entry).options(selectinload(Entry.sources))
        .where(Entry.project_id == project_id, Entry.id == entry_id)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse("Entry not found", status_code=404)

    return templates.TemplateResponse(request, "entries/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
        "linked_sources": [{"slug": s.slug} for s in entry.sources],
    })


@app.get("/projects/{project_id}/entries/{entry_id}/report", response_class=HTMLResponse)
async def entry_report(
    request: Request,
    project_id: UUID,
    entry_id: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render an entry as an interactive report with Explain/What-if buttons on belief references."""
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    entry = (await session.execute(
        select(Entry).where(Entry.project_id == project_id, Entry.id == entry_id)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse("Entry not found", status_code=404)

    return templates.TemplateResponse(request, "reports/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
    })


if settings.llm_enabled:
    @app.get("/projects/{project_id}/ingest", response_class=HTMLResponse)
    async def ingest_form(request: Request, project_id: UUID, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return HTMLResponse("Project not found", status_code=404)
        return templates.TemplateResponse(request, "ingest/form.html", {
            "project": {"id": project_id, "name": project.name},
        })


@app.get("/projects/{project_id}/beliefs/review", response_class=HTMLResponse)
async def beliefs_review_page(
    request: Request,
    project_id: UUID,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    # Get OUT nodes (proposed but not yet accepted)
    out_result = await asyncio.to_thread(rms_api.list_nodes, project_id, status="OUT")
    beliefs = out_result["nodes"]

    return templates.TemplateResponse(request, "beliefs/review.html", {
        "project": {"id": project_id, "name": project.name},
        "beliefs": [{"id": b["id"], "text": b["text"], "source": ""} for b in beliefs],
    })


@app.post("/projects/{project_id}/beliefs/review")
async def beliefs_review_submit(
    request: Request,
    project_id: UUID,
    _user: UserInfo = Depends(verify_auth_web),
):
    """Handle form submission of belief review decisions."""
    form_data = await request.form()

    # Extract decisions from form fields (decision_belief-id = accept|reject|pending)
    decisions = {}
    for key, value in form_data.items():
        if key.startswith("decision_") and value in ("accept", "reject"):
            belief_id = key[len("decision_"):]
            decisions[belief_id] = value

    if not decisions:
        return RedirectResponse(
            f"/projects/{project_id}/beliefs/review", status_code=303
        )

    # Update RMS nodes via assert/retract
    def _apply_decisions():
        for belief_id, decision in decisions.items():
            try:
                if decision == "accept":
                    rms_api.assert_node(project_id, belief_id)
                # "reject" leaves node as OUT (already retracted during proposal)
            except KeyError:
                pass

    await asyncio.to_thread(_apply_decisions)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


def main():
    """Entry point for the reasons-service command."""
    uvicorn.run("reasons_service.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
