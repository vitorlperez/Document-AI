import logging
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.auth import current_user
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.ingestion import router as ingestion_router
from app.api.integrations import router as integrations_router
from app.api.library import router as library_router
from app.api.platform import router as platform_router
from app.api.saved_queries import router as saved_queries_router
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory
from app.core.logging import configure_observability
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


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id", str(uuid4()))
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request complete",
            extra={
                "event": "request_complete",
                "request_id": request_id,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        response.headers["x-request-id"] = request_id
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_observability()
    app = FastAPI(title="Document Intelligence API", version="0.1.0")
    app.state.engine = build_engine(runtime_settings)
    app.state.session_factory = build_session_factory(app.state.engine)
    app.state.settings = runtime_settings
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
        runtime_settings.openai_api_key.get_secret_value() if runtime_settings.openai_api_key else None
    )
    # The browser UI runs on a separate local port during development. Restrict
    # cross-origin requests to the configured public application origin and keep
    # credentialed session requests explicit.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[runtime_settings.public_app_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-Id"],
    )
    app.add_middleware(RequestLogMiddleware)
    app.include_router(health_router)
    app.include_router(auth_router)
    # Fail closed at the router boundary when a new private endpoint is added.
    # FastAPI caches the shared dependency for handlers that also need the user.
    authenticated = [Depends(current_user)]
    app.include_router(platform_router, dependencies=authenticated)
    app.include_router(integrations_router, dependencies=authenticated)
    app.include_router(saved_queries_router, dependencies=authenticated)
    app.include_router(ingestion_router, dependencies=authenticated)
    app.include_router(library_router, dependencies=authenticated)
    return app


app = create_app()
