"""OAuth 2.1 authorization server provider for the MCP endpoint.

Delegates user identity to Google OAuth. Persists clients and tokens
to the database so sessions survive server restarts.
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
from sqlalchemy import delete, select

from reasons_service.db.connection import async_session
from reasons_service.db.models import McpAccessToken, McpClient, McpRefreshToken


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


def _client_from_row(row: McpClient) -> OAuthClientInformationFull:
    cls = _OpenClient if row.is_open else OAuthClientInformationFull
    return cls.model_validate(row.client_data)


def _access_token_from_row(row: McpAccessToken) -> AccessToken:
    return AccessToken(
        token=row.token,
        client_id=row.client_id,
        scopes=row.scopes or [],
        expires_at=row.expires_at,
        resource=row.resource,
        subject=row.subject,
    )


def _refresh_token_from_row(row: McpRefreshToken) -> RefreshToken:
    return RefreshToken(
        token=row.token,
        client_id=row.client_id,
        scopes=row.scopes or [],
        expires_at=row.expires_at,
        subject=row.subject,
    )


class ReasonsOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, google_client_id: str, google_client_secret: str, callback_url: str):
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.callback_url = callback_url

        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._pending_auth: dict[str, dict] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with async_session() as session:
            row = await session.get(McpClient, client_id)
            if row:
                return _client_from_row(row)

        client = _OpenClient(
            client_id=client_id,
            redirect_uris=["https://placeholder.invalid/callback"],
            token_endpoint_auth_method="none",
        )
        async with async_session() as session:
            session.add(McpClient(
                client_id=client_id,
                client_data=client.model_dump(mode="json"),
                is_open=True,
            ))
            await session.commit()
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        async with async_session() as session:
            row = await session.get(McpClient, client_info.client_id)
            if row:
                row.client_data = client_info.model_dump(mode="json")
                row.is_open = isinstance(client_info, _OpenClient)
            else:
                session.add(McpClient(
                    client_id=client_info.client_id,
                    client_data=client_info.model_dump(mode="json"),
                    is_open=isinstance(client_info, _OpenClient),
                ))
            await session.commit()

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
        self._auth_codes.pop(authorization_code.code, None)

        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 86400

        async with async_session() as session:
            session.add(McpAccessToken(
                token=access,
                client_id=client.client_id,
                scopes=authorization_code.scopes,
                expires_at=expires_at,
                resource=authorization_code.resource,
                subject=authorization_code.subject,
            ))
            session.add(McpRefreshToken(
                token=refresh,
                client_id=client.client_id,
                scopes=authorization_code.scopes,
                subject=authorization_code.subject,
            ))
            await session.commit()

        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            token_type="Bearer",
            expires_in=86400,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with async_session() as session:
            row = await session.get(McpAccessToken, token)
            if row:
                return _access_token_from_row(row)
        return None

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with async_session() as session:
            row = await session.get(McpRefreshToken, refresh_token)
            if row and row.client_id == client.client_id:
                return _refresh_token_from_row(row)
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 86400

        async with async_session() as session:
            # Delete old refresh token
            await session.execute(
                delete(McpRefreshToken).where(McpRefreshToken.token == refresh_token.token)
            )
            # Revoke old access tokens for this client+subject
            await session.execute(
                delete(McpAccessToken).where(
                    McpAccessToken.client_id == client.client_id,
                    McpAccessToken.subject == refresh_token.subject,
                )
            )
            # Issue new tokens
            session.add(McpAccessToken(
                token=access,
                client_id=client.client_id,
                scopes=scopes or refresh_token.scopes,
                expires_at=expires_at,
                subject=refresh_token.subject,
            ))
            session.add(McpRefreshToken(
                token=new_refresh,
                client_id=client.client_id,
                scopes=scopes or refresh_token.scopes,
                subject=refresh_token.subject,
            ))
            await session.commit()

        return OAuthToken(
            access_token=access,
            refresh_token=new_refresh,
            token_type="Bearer",
            expires_in=86400,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with async_session() as session:
            if isinstance(token, AccessToken):
                await session.execute(
                    delete(McpAccessToken).where(McpAccessToken.token == token.token)
                )
            elif isinstance(token, RefreshToken):
                await session.execute(
                    delete(McpRefreshToken).where(McpRefreshToken.token == token.token)
                )
            await session.commit()
