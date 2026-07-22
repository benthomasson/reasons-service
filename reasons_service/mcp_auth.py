"""OAuth 2.1 authorization server provider for the MCP endpoint.

Delegates user identity to Google OAuth. Stores tokens in memory
(acceptable for single-server deployment — tokens are lost on restart,
clients re-authenticate automatically).
"""

import secrets
import time
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl


class _OpenClient(OAuthClientInformationFull):
    """Client that accepts any redirect_uri. Used for auto-registered clients
    where we don't know the redirect URIs in advance."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None:
            return redirect_uri
        if self.redirect_uris and len(self.redirect_uris) == 1:
            return self.redirect_uris[0]
        from mcp.shared.auth import InvalidRedirectUriError
        raise InvalidRedirectUriError("redirect_uri must be specified")


class ReasonsOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, google_client_id: str, google_client_secret: str, callback_url: str):
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.callback_url = callback_url

        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        # Maps state → {params, client_id} for linking Google callback to MCP auth request
        self._pending_auth: dict[str, dict] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = self._clients.get(client_id)
        if client:
            return client
        # Auto-register unknown clients (e.g. Claude Desktop with pre-configured
        # credentials that skips dynamic registration). Security comes from the
        # Google OAuth step, not from MCP client_secret validation.
        client = _OpenClient(
            client_id=client_id,
            redirect_uris=["https://placeholder.invalid/callback"],
            token_endpoint_auth_method="none",
        )
        self._clients[client_id] = client
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        state = secrets.token_urlsafe(32)
        self._pending_auth[state] = {
            "params": params,
            "client_id": client.client_id,
        }

        google_params = {
            "client_id": self.google_client_id,
            "redirect_uri": self.callback_url,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(google_params)}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code and code.client_id == client.client_id and code.expires_at > time.time():
            return code
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        del self._auth_codes[authorization_code.code]

        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 86400

        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=expires_at,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )
        self._refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            subject=authorization_code.subject,
        )

        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            token_type="Bearer",
            expires_in=86400,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self._access_tokens.get(token)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if rt and rt.client_id == client.client_id:
            return rt
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        del self._refresh_tokens[refresh_token.token]
        # Revoke old access tokens for this client+subject
        to_delete = [
            k for k, v in self._access_tokens.items()
            if v.client_id == client.client_id and v.subject == refresh_token.subject
        ]
        for k in to_delete:
            del self._access_tokens[k]

        access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 86400

        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            expires_at=expires_at,
            subject=refresh_token.subject,
        )
        self._refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            subject=refresh_token.subject,
        )

        return OAuthToken(
            access_token=access,
            refresh_token=new_refresh,
            token_type="Bearer",
            expires_in=86400,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
