"""Authentication: Google OAuth + bearer token with dev-mode bypass."""

import hmac
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.config import settings
from reasons_service.db.connection import get_session
from reasons_service.db.models import User
from reasons_service.rbac import UserInfo, Role

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)

# Google's public key endpoint for ID token verification
_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_id_token_cache: dict[str, dict] = {}  # token -> {email, exp}


# --- OAuth routes ---


@router.get("/login")
async def login(request: Request):
    from reasons_service.app import oauth

    if not oauth:
        return HTMLResponse("OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", status_code=501)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/callback")
async def auth_callback(request: Request, session: AsyncSession = Depends(get_session)):
    from reasons_service.app import oauth

    if not oauth:
        return HTMLResponse("OAuth not configured", status_code=501)

    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo", {})
    email = userinfo.get("email", "")

    if not email:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;display:flex;justify-content:center;"
            "align-items:center;height:100vh;'><div style='text-align:center'>"
            "<h1>Access Denied</h1><p>Could not retrieve email from Google.</p>"
            "</div></body></html>",
            status_code=403,
        )

    email = email.strip().lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;display:flex;justify-content:center;"
            "align-items:center;height:100vh;'><div style='text-align:center'>"
            "<h1>Access Denied</h1><p>Your account is not authorized for Reasons Service.</p>"
            "</div></body></html>",
            status_code=403,
        )

    # Clear existing session to prevent session fixation
    request.session.clear()
    request.session["user_email"] = email
    request.session["user_name"] = userinfo.get("name", email)
    return RedirectResponse(url="/projects")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/login")
    response.delete_cookie("session")
    return response


# --- Google ID token verification ---


async def _verify_google_id_token(token: str) -> str | None:
    """Verify a Google ID token and return the email, or None if invalid.

    Uses Google's tokeninfo endpoint for verification. Results are
    cached briefly to avoid repeated network calls for the same token.
    """
    import time

    # Check cache
    cached = _id_token_cache.get(token)
    if cached and cached.get("exp", 0) > time.time():
        return cached["email"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _GOOGLE_TOKENINFO_URL,
                params={"id_token": token},
                timeout=10.0,
            )
        if resp.status_code != 200:
            return None
        info = resp.json()

        # Verify the token was issued for our client
        aud = info.get("aud", "")
        if settings.google_client_id and aud != settings.google_client_id:
            logger.warning("ID token audience mismatch: %s != %s", aud, settings.google_client_id)
            return None

        email = info.get("email", "")
        if not email or info.get("email_verified") != "true":
            return None

        # Cache the result
        _id_token_cache[token] = {"email": email, "exp": int(info.get("exp", 0))}

        # Prune expired cache entries
        now = time.time()
        expired = [k for k, v in _id_token_cache.items() if v["exp"] <= now]
        for k in expired:
            del _id_token_cache[k]

        return email
    except Exception:
        logger.exception("Failed to verify Google ID token")
        return None


def _resolve_visible_tags(db_user: User) -> list[str] | None:
    """Return the user's visible_tags, or None if admin (unrestricted)."""
    if db_user.role == Role.ADMIN:
        return None
    return db_user.visible_tags or []


# --- Dual auth dependency ---


async def verify_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    """Authenticate via bearer token, Google ID token, OAuth session, or dev-mode bypass."""

    # 1. Static API key (programmatic access)
    if credentials and settings.api_key and hmac.compare_digest(credentials.credentials, settings.api_key):
        user = UserInfo(identity="api", role=Role.ADMIN)
        request.state.user = user
        return user

    # 2. Google ID token (CLI/programmatic access with per-user identity)
    if credentials and settings.google_client_id:
        email = await _verify_google_id_token(credentials.credentials)
        if email:
            email = email.strip().lower()
            result = await session.execute(select(User).where(User.email == email))
            db_user = result.scalar_one_or_none()
            if db_user:
                user = UserInfo(
                    identity=email,
                    role=db_user.role,
                    display_name=db_user.display_name,
                    visible_tags=_resolve_visible_tags(db_user),
                )
                request.state.user = user
                return user
            else:
                raise HTTPException(status_code=403, detail="User not registered")

    # 3. OAuth session (browser access)
    email = request.session.get("user_email")
    if email:
        result = await session.execute(select(User).where(User.email == email))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=403, detail="User not registered")
        user = UserInfo(
            identity=email,
            role=db_user.role,
            display_name=db_user.display_name,
            visible_tags=_resolve_visible_tags(db_user),
        )
        request.state.user = user
        return user

    # 3. Dev mode — no OAuth configured, allow anonymous access
    if not settings.google_client_id:
        user = UserInfo(identity="dev", role=Role.ADMIN, display_name="Developer")
        request.state.user = user
        return user

    raise HTTPException(status_code=401, detail="Not authenticated")


async def verify_auth_or_public(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    """Try auth first (preserving real identity); fall back to public access."""
    try:
        return await verify_auth(request, credentials, session)
    except HTTPException as e:
        if e.status_code != 401:
            raise
    # Auth failed with 401 — check if this is a public project
    project_id = request.path_params.get("project_id")
    if project_id:
        from uuid import UUID
        from reasons_service.db.models import Project
        result = await session.execute(
            select(Project.public).where(Project.id == UUID(str(project_id)))
        )
        row = result.first()
        if row and row.public:
            user = UserInfo(identity="public", role=Role.READER)
            request.state.user = user
            return user
    raise HTTPException(status_code=401, detail="Not authenticated")


class _LoginRedirect(Exception):
    """Raised to trigger a redirect to /login for unauthenticated web requests."""
    pass


async def verify_auth_web(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    """Same as verify_auth but redirects to /login for unauthenticated browser requests."""
    try:
        return await verify_auth(request, credentials, session)
    except HTTPException as e:
        if e.status_code == 401:
            raise _LoginRedirect()
        raise
