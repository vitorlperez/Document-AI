"""ASGI entrypoint: `uvicorn app.mcp_server.asgi:app`. Stateless Streamable HTTP, resource server only."""

import contextvars
import time
from urllib.parse import urlsplit

import redis
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.access.audit import AuditWriter
from app.access.models import OrganizationAccessSettings
from app.access.principal import (
    ApiKeyAuthenticator,
    InsufficientScope,
    InvalidCredential,
    Principal,
)
from app.access.ratelimit import RateLimiter, RedisRateLimiter
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory
from app.mcp_server import tools
from app.mcp_server.auth import (
    AuthKitTokenVerifier,
    InvalidToken,
    McpPrincipalResolver,
    jwks_key_resolver,
)
from app.mcp_server.server import build_server

_principal: contextvars.ContextVar[Principal] = contextvars.ContextVar("mcp_principal")


class McpAuthMiddleware:
    """Bearer validation, per-call principal resolution and rate limiting in front of the MCP endpoint."""

    def __init__(self, app: ASGIApp, *, path: str, metadata_url: str, verifier: AuthKitTokenVerifier,
                 session_factory, rate_limiter: RateLimiter, limit: int, audit: AuditWriter, static_keys: bool = False):
        self.app, self.path, self.metadata_url = app, path, metadata_url
        self.static_keys = static_keys
        self.verifier, self.factory, self.limiter, self.limit, self.audit = verifier, session_factory, rate_limiter, limit, audit

    def _unauthorized(self, with_error: bool) -> JSONResponse:
        challenge = f'Bearer resource_metadata="{self.metadata_url}"'
        if with_error:
            challenge += ', error="invalid_token"'
        return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": challenge})

    def _resolve(self, token: str) -> Principal:
        if self.static_keys and token.startswith("arq_"):
            with self.factory() as session:
                try:
                    principal = ApiKeyAuthenticator(session).authenticate(token)
                except InvalidCredential as error:
                    raise InvalidToken from error
                access_settings = session.get(OrganizationAccessSettings, principal.organization_id)
                if access_settings is None or not access_settings.mcp_enabled:
                    raise InvalidToken
                session.commit()  # last-used bookkeeping
                return principal
        verified = self.verifier.verify(token)
        with self.factory() as session:  # every request: revocation/deactivation apply immediately
            return McpPrincipalResolver(session).resolve(verified.subject)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].rstrip("/") != self.path:
            await self.app(scope, receive, send)
            return
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await self._unauthorized(False)(scope, receive, send)
            return
        try:
            principal = await run_in_threadpool(self._resolve, token.strip())
        except InvalidToken:
            await self._unauthorized(True)(scope, receive, send)
            return
        try:
            decision = self.limiter.hit(key=f"mcp:{principal.credential_id or principal.user_id}", limit=self.limit)
        except Exception:  # noqa: BLE001 — limiter down: fail closed
            await JSONResponse({"error": "rate limiter unavailable"}, status_code=503,
                               headers={"Retry-After": "5"})(scope, receive, send)
            return
        if not decision.allowed:
            await run_in_threadpool(
                self.audit.record, principal=principal, organization_id=principal.organization_id,
                channel="mcp", action="request", status="rate_limited", http_status=429, request_id=None,
                latency_ms=0)
            await JSONResponse({"error": "rate limit exceeded"}, status_code=429,
                               headers={"Retry-After": str(decision.reset_seconds)})(scope, receive, send)
            return
        reset = _principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(reset)


def build_mcp_app(settings: Settings, session_factory, rate_limiter: RateLimiter,
                  verifier: AuthKitTokenVerifier) -> Starlette:
    resource = urlsplit(settings.mcp_resource_url or "")
    path = resource.path or "/mcp"
    origin = f"{resource.scheme}://{resource.netloc}"
    metadata_path = f"/.well-known/oauth-protected-resource{path}"
    audit = AuditWriter(session_factory)

    def run_sync(name: str, arguments: dict[str, str], principal: Principal) -> dict[str, object] | None:
        started, status, count, document_id, result = time.perf_counter(), "ok", None, None, None
        query = arguments.get("query")
        try:
            with session_factory() as session:
                if name == "search":
                    result = tools.run_search(session, principal, arguments["query"])
                    count = len(result["results"])
                elif name == "fetch":
                    result = tools.run_fetch(session, principal, arguments["id"])
                    count = 1
                    document_id = result["id"]
                else:
                    result = tools.run_list_sources(session, principal)
                    count = len(result["sources"])
        except tools.ToolNotFound:
            status, result = "denied", None
        except InsufficientScope:
            status, result = "denied", None
        except Exception:
            status = "error"
            raise
        finally:
            audit.record(
                principal=principal, organization_id=principal.organization_id, channel="mcp", action=name,
                status=status, http_status={"ok": 200, "denied": 404}.get(status, 500), request_id=None,
                latency_ms=round((time.perf_counter() - started) * 1000), result_count=count, query=query,
                document_id=_uuid(document_id),
            )
        return result

    async def run_tool(name: str, arguments: dict[str, str]) -> dict[str, object] | None:
        return await run_in_threadpool(run_sync, name, arguments, _principal.get())

    hosts = [host.strip() for host in settings.mcp_allowed_hosts.split(",") if host.strip()]
    if not hosts:
        if resource.scheme not in {"http", "https"} or not resource.hostname:
            raise RuntimeError("MCP_ALLOWED_HOSTS or an absolute HTTP(S) MCP_RESOURCE_URL is required")
        hosts = [resource.netloc]
    server = build_server(run_tool)
    app = server.streamable_http_app(
        streamable_http_path=path, stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[]),
    )

    async def protected_resource(_request):
        return JSONResponse({
            "resource": settings.mcp_resource_url, "authorization_servers": [settings.mcp_issuer_url],
            "bearer_methods_supported": ["header"], "scopes_supported": [],
        })

    async def live(_request):
        return PlainTextResponse("ok")

    app.router.routes.extend([Route(metadata_path, protected_resource), Route("/health/live", live)])
    app.add_middleware(
        McpAuthMiddleware, path=path, metadata_url=origin + metadata_path, verifier=verifier,
        session_factory=session_factory, rate_limiter=rate_limiter, limit=settings.mcp_rate_limit_per_minute,
        audit=audit, static_keys=settings.mcp_static_key_enabled,
    )
    return app


def _uuid(value):
    from uuid import UUID
    return UUID(value) if value else None


def _build_from_settings() -> Starlette:
    settings = get_settings()
    if not (settings.mcp_resource_url and settings.mcp_issuer_url and settings.mcp_jwks_url):
        raise RuntimeError("MCP_RESOURCE_URL, MCP_ISSUER_URL and MCP_JWKS_URL are required")
    verifier = AuthKitTokenVerifier(
        issuer=settings.mcp_issuer_url, resource=settings.mcp_resource_url,
        key_resolver=jwks_key_resolver(settings.mcp_jwks_url))
    factory = build_session_factory(build_engine(settings))
    return build_mcp_app(settings, factory, RedisRateLimiter(redis.Redis.from_url(settings.redis_url)), verifier)


def __getattr__(name: str):  # `uvicorn app.mcp_server.asgi:app` builds lazily; importing stays side-effect free
    if name == "app":
        instance = _build_from_settings()
        globals()["app"] = instance
        return instance
    raise AttributeError(name)

