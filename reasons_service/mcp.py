"""MCP server mounted at /mcp — exposes reasons-service tools over streamable HTTP."""

import base64
import json
import secrets
import time

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from reasons_service.config import settings

BASE_URL = settings.mcp_base_url
TIMEOUT = 120.0

# --- Auth configuration (conditional on Google OAuth being set up) ---

_auth_kwargs: dict = {}
_provider = None

if settings.google_client_id and settings.google_client_secret:
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

    from reasons_service.mcp_auth import ReasonsOAuthProvider

    _provider = ReasonsOAuthProvider(
        google_client_id=settings.google_client_id,
        google_client_secret=settings.google_client_secret,
        callback_url=f"{settings.mcp_issuer_url}/oauth/callback",
    )
    _auth_kwargs = {
        "auth_server_provider": _provider,
        "auth": AuthSettings(
            issuer_url=settings.mcp_issuer_url,
            resource_server_url=settings.mcp_issuer_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
    }

mcp = FastMCP(
    "reasons-service",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security={"enable_dns_rebinding_protection": False},
    **_auth_kwargs,
)


# --- Google OAuth callback (only when auth is enabled) ---

if _provider:

    @mcp.custom_route("/oauth/callback", methods=["GET"])
    async def google_oauth_callback(request: Request) -> Response:
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            return HTMLResponse(f"Google OAuth error: {error}", status_code=400)
        if not code or not state:
            return HTMLResponse("Missing code or state parameter", status_code=400)

        pending = _provider._pending_auth.pop(state, None)
        if not pending:
            return HTMLResponse("Invalid or expired state", status_code=400)

        mcp_params = pending["params"]
        mcp_client_id = pending["client_id"]

        # Exchange Google auth code for tokens
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": f"{settings.mcp_issuer_url}/oauth/callback",
                    "grant_type": "authorization_code",
                },
                timeout=10.0,
            )

        if resp.status_code != 200:
            return HTMLResponse(f"Google token exchange failed: {resp.text}", status_code=502)

        google_tokens = resp.json()
        id_token = google_tokens.get("id_token", "")

        # Decode Google ID token payload (base64url, no signature verification needed
        # since we just got it directly from Google's token endpoint over HTTPS)
        try:
            payload = id_token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return HTMLResponse("Failed to decode Google ID token", status_code=502)

        email = claims.get("email", "").strip().lower()
        if not email or not claims.get("email_verified", False):
            return HTMLResponse("Email not verified by Google", status_code=403)

        # Verify user exists in database
        from sqlalchemy import select

        from reasons_service.db.connection import async_session
        from reasons_service.db.models import User

        async with async_session() as session:
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

        # Issue MCP authorization code
        from mcp.server.auth.provider import AuthorizationCode, construct_redirect_uri

        mcp_code = secrets.token_urlsafe(32)
        _provider._auth_codes[mcp_code] = AuthorizationCode(
            code=mcp_code,
            scopes=mcp_params.scopes or [],
            expires_at=time.time() + 600,
            client_id=mcp_client_id,
            code_challenge=mcp_params.code_challenge,
            redirect_uri=mcp_params.redirect_uri,
            redirect_uri_provided_explicitly=mcp_params.redirect_uri_provided_explicitly,
            resource=mcp_params.resource,
            subject=email,
        )

        redirect_url = construct_redirect_uri(
            str(mcp_params.redirect_uri),
            code=mcp_code,
            state=mcp_params.state,
        )
        return RedirectResponse(url=redirect_url, status_code=302)


# --- Helpers ---


def _headers() -> dict[str, str]:
    if settings.api_key:
        return {"Authorization": f"Bearer {settings.api_key}"}
    return {}


async def _resolve(domain: str) -> str:
    if len(domain) == 36 and domain.count("-") == 4:
        return domain
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/resolve",
            params={"name": domain},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["id"]


# --- Tier 1: Core knowledge access ---


@mcp.tool()
async def deep_search(query: str, domain: str) -> str:
    """Search beliefs and source documents with IDF-ranked results. No LLM call, sub-second response.

    This is the recommended search tool. It runs dual-path retrieval across
    the belief network and source document chunks, returning pre-ranked
    context ready for synthesis.

    Args:
        query: The question or search terms
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/deep-search",
            params={"q": query},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)



@mcp.tool()
async def search(query: str, domain: str) -> str:
    """Full-text search across beliefs, entries, and source documents.

    Returns matching beliefs (with IN/OUT truth values), entry titles,
    and source chunk snippets.

    Args:
        query: Search terms
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/search",
            params={"q": query},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


# --- Tier 2: Belief exploration ---


@mcp.tool()
async def explain_belief(node_id: str, domain: str) -> str:
    """Explain why a belief is IN or OUT by tracing its justification chain.

    Args:
        node_id: The belief ID to explain
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        belief = await client.get(
            f"{BASE_URL}/api/domains/{pid}/beliefs/{node_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        belief.raise_for_status()
        explanation = await client.get(
            f"{BASE_URL}/api/domains/{pid}/beliefs/{node_id}/explain",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        explanation.raise_for_status()
        return json.dumps({"belief": belief.json(), "explanation": explanation.json()}, indent=2)


@mcp.tool()
async def what_if(node_id: str, action: str = "retract", domain: str = "") -> str:
    """Simulate retracting or asserting a belief without modifying the database.

    Shows the cascade: which beliefs would go OUT (retract) or come back IN (assert).

    Args:
        node_id: The belief ID to simulate
        action: "retract" or "assert"
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/beliefs/{node_id}/what-if",
            params={"action": action},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def get_belief(node_id: str, domain: str) -> str:
    """Get full details for a specific belief including justifications and dependents.

    Args:
        node_id: The belief ID
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/beliefs/{node_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def find_issues(domain: str) -> str:
    """Find gated beliefs — beliefs that are OUT because one or more antecedents are OUT.

    These represent blocked conclusions: things the knowledge base would believe
    if the missing dependencies were satisfied. Useful for identifying what
    needs to be fixed or investigated.

    Args:
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/issues",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return json.dumps({"gated": data.get("gated", [])}, indent=2)


@mcp.tool()
async def list_beliefs(status: str = "", domain: str = "") -> str:
    """List beliefs in the knowledge base.

    Args:
        status: Filter by truth value -- "IN", "OUT", or empty for all
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    params = {}
    if status:
        params["status"] = status
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/beliefs",
            params=params,
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


# --- Tier 3: Content browsing ---


@mcp.tool()
async def list_domains() -> str:
    """List all available knowledge bases with belief, entry, and source counts."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def list_topics(domain: str) -> str:
    """List the main topics covered by a domain's knowledge base.

    Returns topic areas with belief counts, giving a quick overview
    of what the domain covers. Use this before searching to understand
    the knowledge base structure.

    Args:
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/topics",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        topics = resp.json()
        if not topics:
            gen = await client.post(
                f"{BASE_URL}/api/domains/{pid}/topics/generate",
                headers=_headers(),
                timeout=TIMEOUT,
            )
            gen.raise_for_status()
            resp = await client.get(
                f"{BASE_URL}/api/domains/{pid}/topics",
                headers=_headers(),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            topics = resp.json()
        return json.dumps(topics, indent=2)


@mcp.tool()
async def list_entries(topic: str = "", domain: str = "") -> str:
    """List analysis entries (reports, findings, assessments).

    Args:
        topic: Filter by topic slug, or empty for all entries
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    params = {}
    if topic:
        params["topic"] = topic
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/entries",
            params=params,
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def get_entry(entry_id: str, domain: str) -> str:
    """Read the full content of an analysis entry.

    Args:
        entry_id: The entry ID
        domain: Domain name or UUID
    """
    pid = await _resolve(domain)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/domains/{pid}/entries/{entry_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
