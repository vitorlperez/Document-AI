"""Validate OAuth access tokens for the MCP resource server and map them to a scoped Principal.

The authorization server (WorkOS AuthKit, or a fake in tests) signs the token; this module only
verifies it (audience-bound, RS256) and never forwards it to any other service.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.models import (
    SCOPE_DOCUMENTS,
    SCOPE_SEARCH,
    McpConnection,
    OrganizationAccessSettings,
)
from app.access.principal import Principal
from app.identity.models import AuthIdentity
from app.ingestion.service import SyncAccessDenied
from app.library.service import LibraryService

KeyResolver = Callable[[str], object]


class InvalidToken(Exception):
    """Bad signature/audience/issuer/expiry, unknown subject or no active binding — indistinguishable."""


@dataclass(frozen=True)
class VerifiedToken:
    subject: str
    scopes: list[str]
    client_id: str
    expires_at: int | None


class AuthKitTokenVerifier:
    def __init__(self, *, issuer: str, resource: str, key_resolver: KeyResolver):
        self.issuer, self.resource, self._key_resolver = issuer, resource, key_resolver

    def verify(self, token: str) -> VerifiedToken:
        try:
            key = self._key_resolver(token)
            claims = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.resource, issuer=self.issuer,
                options={"require": ["exp", "aud", "iss", "sub"]},
            )
        except Exception as error:
            raise InvalidToken from error
        scope = claims.get("scope") or ""
        scopes = scope.split() if isinstance(scope, str) else list(scope)
        return VerifiedToken(
            subject=str(claims["sub"]), scopes=scopes,
            client_id=str(claims.get("client_id") or claims.get("azp") or ""), expires_at=claims.get("exp"),
        )


def jwks_key_resolver(jwks_url: str) -> KeyResolver:
    """Production resolver: fetch and cache the authorization server's signing keys."""
    client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return lambda token: client.get_signing_key_from_jwt(token).key


class McpPrincipalResolver:
    def __init__(self, session: Session):
        self.session = session

    def resolve(self, subject: str) -> Principal:
        user_id = self.session.scalar(select(AuthIdentity.user_id).where(
            AuthIdentity.provider == "workos", AuthIdentity.provider_subject == subject))
        if user_id is None:
            raise InvalidToken
        connection = self.session.scalar(select(McpConnection).where(
            McpConnection.user_id == user_id, McpConnection.revoked_at.is_(None)))
        if connection is None:
            raise InvalidToken
        settings = self.session.get(OrganizationAccessSettings, connection.organization_id)
        if settings is None or not settings.mcp_enabled:
            raise InvalidToken
        principal = Principal(
            organization_id=connection.organization_id, user_id=user_id, channel="mcp",
            scopes=frozenset({SCOPE_SEARCH, SCOPE_DOCUMENTS}),
            node_ids=tuple(UUID(item) for item in connection.node_ids) if connection.node_ids else None,
        )
        try:
            LibraryService(self.session).require_member(scope=principal.scope, user_id=user_id)
        except SyncAccessDenied as error:
            raise InvalidToken from error
        return principal
