import logging
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.access.ratelimit import RedisRateLimiter
from app.api.access_admin import router as access_admin_router
from app.api.auth import current_user
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.ingestion import router as ingestion_router
from app.api.integrations import router as integrations_router
from app.api.library import router as library_router
from app.api.mcp_admin import router as mcp_admin_router
from app.api.platform import router as platform_router
from app.api.public_v1 import router as public_v1_router
from app.api.saved_queries import router as saved_queries_router
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory
from app.core.logging import configure_observability, provider_call_count, request_context
from app.identity.auth import WorkOSAuthKitGateway
from app.ingestion.dispatch import CeleryIngestionDispatcher
from app.ingestion.tasks import create_celery_app
from app.integrations.google_drive import GoogleDriveOAuthClient, GoogleOAuthUnavailable
from app.knowledge.questions import OpenAIQuestionProvider
from app.organizations.delivery import ResendInvitationDelivery


class UnconfiguredGoogleDrivePort:
    def authorization_url(self, *, state: str, scope: str) -> str: raise GoogleOAuthUnavailable("Google OAuth is not configured")
    def exchange_code(self, *, code: str): raise GoogleOAuthUnavailable("Google OAuth is not configured")
    def list_folders(self, *, credentials): raise GoogleOAuthUnavailable("Google OAuth is not configured")

logger = logging.getLogger("document_intelligence.request")


_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
        start = time.perf_counter()

        def log_complete(status: int) -> None:
            logger.info(
                "request complete",
                extra={
                    "event": "request_complete",
                    "request_id": request_id,
                    "path": request.url.path,
                    "status": status,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                    "provider_call_count": provider_call_count(),
                },
            )

        with request_context(request_id):
            try:
                response = await call_next(request)
            except Exception:
                log_complete(500)
                raise
            log_complete(response.status_code)
        response.headers["x-request-id"] = request_id
        return response


class CookieOriginMiddleware(BaseHTTPMiddleware):
    """Reject browser cookie mutations outside the configured application origin."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        settings = request.app.state.settings
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and settings.auth_session_cookie_name in request.cookies:
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site")
            expected = urlsplit(settings.public_app_url)
            supplied = urlsplit(origin) if origin else None
            allowed = bool(
                supplied
                and supplied.scheme == expected.scheme
                and supplied.netloc == expected.netloc
                and supplied.path in {"", "/"}
                and not supplied.query
                and not supplied.fragment
            )
            # Development supports local scripts without Origin; production
            # requires it, including for logout and newly added routes.
            if fetch_site == "cross-site" or (origin and not allowed) or (not origin and settings.environment != "development"):
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_observability()
    app = FastAPI(title="Document Intelligence API", version="0.1.0")
    app.state.engine = build_engine(runtime_settings)
    app.state.session_factory = build_session_factory(app.state.engine)
    app.state.settings = runtime_settings
    app.state.rate_limiter = RedisRateLimiter(redis.Redis.from_url(runtime_settings.redis_url, socket_timeout=1, socket_connect_timeout=1))
    app.state.auth_gateway = WorkOSAuthKitGateway(
        api_key=runtime_settings.workos_api_key.get_secret_value() if runtime_settings.workos_api_key else None,
        client_id=runtime_settings.workos_client_id,
        redirect_uri=runtime_settings.workos_redirect_uri,
    )
    app.state.invitation_delivery = ResendInvitationDelivery(
        api_key=runtime_settings.resend_api_key.get_secret_value() if runtime_settings.resend_api_key else None,
        from_email=runtime_settings.invitation_from_email,
    )
    app.state.google_drive_port = GoogleDriveOAuthClient(
        client_id=runtime_settings.google_oauth_client_id,
        client_secret=runtime_settings.google_oauth_client_secret.get_secret_value() if runtime_settings.google_oauth_client_secret else None,
        redirect_uri=runtime_settings.google_oauth_redirect_uri,
    )
    app.state.ingestion_dispatcher = CeleryIngestionDispatcher(create_celery_app(runtime_settings))
    app.state.semantic_provider = OpenAIQuestionProvider(
        runtime_settings.openai_api_key.get_secret_value() if runtime_settings.openai_api_key else None,
        evidence_context_chars=runtime_settings.evidence_context_chars,
        fence_sources_enabled=runtime_settings.source_fencing_enabled,
    )
    # The browser UI runs on a separate local port during development. Restrict
    # cross-origin requests to the configured public application origin and keep
    # credentialed session requests explicit.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[runtime_settings.public_app_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-Id"],
    )
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(CookieOriginMiddleware)
    app.include_router(health_router)
    app.include_router(auth_router)
    # Fail closed at the router boundary when a new private endpoint is added.
    # FastAPI caches the shared dependency for handlers that also need the user.
    app.include_router(public_v1_router)

    @app.get("/v1/openapi.json", include_in_schema=False)
    def public_openapi() -> dict:
        return get_openapi(title="Arquivio Public API", version="1.0.0",
                          routes=public_v1_router.routes,
                          description="Read-only organization library. Bearer API keys.")

    authenticated = [Depends(current_user)]
    app.include_router(access_admin_router, dependencies=authenticated)
    app.include_router(mcp_admin_router, dependencies=authenticated)
    app.include_router(platform_router, dependencies=authenticated)
    app.include_router(integrations_router, dependencies=authenticated)
    app.include_router(saved_queries_router, dependencies=authenticated)
    app.include_router(ingestion_router, dependencies=authenticated)
    app.include_router(library_router, dependencies=authenticated)
    return app


app = create_app()
