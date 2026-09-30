"""Versioned public API (/v1): Bearer API keys, scopes, rate limits, audit, OpenAPI."""

import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.audit import AuditWriter
from app.access.models import SCOPE_ASK, SCOPE_DOCUMENTS, SCOPE_SEARCH
from app.access.principal import (
    ApiKeyAuthenticator,
    InsufficientScope,
    InvalidCredential,
    Principal,
)
from app.access.scope import ScopedAccess
from app.api.auth import database_session
from app.audit_usage.service import UsageLimitExceeded
from app.core.logging import current_request_id
from app.ingestion.service import SyncAccessDenied
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.agent import agent_service_from_settings
from app.knowledge.models import Document
from app.knowledge.presentation import serialize_question_result
from app.knowledge.questions import AIProviderUnavailable, QuestionService
from app.knowledge.retrieval import RetrievalService
from app.knowledge.untrusted import UNTRUSTED_NOTICE
from app.library.service import LibraryService


IP_RATE_LIMIT = 600  # Per peer IP, before any credential/database work.


def _audit_allowed(request: Request, principal: Principal, code: int) -> bool:
    if code not in {403, 429}:
        return True
    try:
        return request.app.state.rate_limiter.hit(
            key=f"audit:{principal.credential_id}:{request.scope['route'].name}:{code}", limit=1,
        ).allowed
    except Exception:
        return False  # Do not turn a limiter outage into an unbounded denial audit stream.


class AuditedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            request.state.started_at = time.perf_counter()
            code = 500
            try:
                response = await original(request)
                code = response.status_code
                return response
            except HTTPException as error:
                code = error.status_code
                raise
            except RequestValidationError:
                code = 422
                raise
            finally:
                principal = getattr(request.state, "principal", None)
                if principal is not None and _audit_allowed(request, principal, code):
                    metadata = getattr(request.state, "audit_metadata", {})
                    outcome = "ok" if code < 400 else "rate_limited" if code == 429 else "denied" if code in {403, 404} else "error"
                    AuditWriter(request.app.state.session_factory).record(
                        principal=principal, organization_id=principal.organization_id,
                        channel=principal.channel, action=metadata.get("action", self.name)[:40],
                        status=outcome, http_status=code, request_id=current_request_id(),
                        latency_ms=round((time.perf_counter() - request.state.started_at) * 1000),
                        result_count=metadata.get("result_count"), query=metadata.get("query"),
                        document_id=metadata.get("document_id"),
                    )
                elif code == 401:
                    logging.getLogger(__name__).warning("invalid API credential", extra={"event": "api_auth_failed"})
        return handler


router = APIRouter(prefix="/v1", tags=["public-api"], route_class=AuditedRoute)
_bearer = HTTPBearer(auto_error=False, scheme_name="ApiKey",
                     description="Organization API key: `Authorization: Bearer arq_<prefix>_<secret>`")


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)
    node_ids: list[UUID] | None = Field(default=None, max_length=20)


class AskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    node_ids: list[UUID] | None = Field(default=None, max_length=20)


def limit_peer(request: Request) -> None:
    # Use the server peer address; caller-controlled forwarded headers are not trusted here.
    peer = request.client.host if request.client else "unknown"
    try:
        decision = request.app.state.rate_limiter.hit(key=f"ip:{peer}:api", limit=IP_RATE_LIMIT)
    except Exception as error:
        raise HTTPException(503, "rate limiter unavailable", headers={"Retry-After": "5"}) from error
    if not decision.allowed:
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(decision.reset_seconds)})


def principal_dep(
    request: Request, _peer_limit: None = Depends(limit_peer),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(database_session),
) -> Principal:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key",
                            headers={"WWW-Authenticate": 'Bearer realm="arquivio"'})
    try:
        principal = ApiKeyAuthenticator(session).authenticate(credentials.credentials)
    except InvalidCredential as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key",
                            headers={"WWW-Authenticate": 'Bearer realm="arquivio"'}) from error
    session.commit()  # Finish last-used update before the independent audit transaction.
    request.state.principal = principal
    return principal


def guarded(scope_name: str, bucket: str, *, cap: str | None = None):
    def dependency(request: Request, response: Response, principal: Principal = Depends(principal_dep)) -> Principal:
        try:
            principal.require(scope_name)
        except InsufficientScope as error:
            _record(request, principal, bucket, "denied", 403)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"insufficient scope: {error.needed}") from error
        settings = request.app.state.settings
        limit = principal.rate_limit_per_minute
        if cap == "ask":
            limit = min(limit, settings.api_ask_rate_limit_per_minute)
        try:
            per_key = request.app.state.rate_limiter.hit(key=f"key:{principal.credential_id}:api", limit=limit)
            per_org = request.app.state.rate_limiter.hit(
                key=f"org:{principal.organization_id}:api", limit=settings.api_org_rate_limit_per_minute)
        except Exception as error:  # Redis down: fail closed, this endpoint can cost money
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "rate limiter unavailable",
                                headers={"Retry-After": "5"}) from error
        response.headers.update({"RateLimit-Limit": str(per_key.limit), "RateLimit-Remaining": str(per_key.remaining),
                                 "RateLimit-Reset": str(per_key.reset_seconds)})
        if not per_key.allowed or not per_org.allowed:
            _record(request, principal, bucket, "rate_limited", 429)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded",
                                headers={"Retry-After": str(max(per_key.reset_seconds, per_org.reset_seconds)),
                                         "RateLimit-Limit": str(per_key.limit),
                                         "RateLimit-Remaining": "0",
                                         "RateLimit-Reset": str(max(per_key.reset_seconds, per_org.reset_seconds))})
        request.state.started_at = time.perf_counter()
        return principal
    return dependency


def _record(request: Request, principal: Principal, action: str, outcome: str, http_status: int,
            *, result_count: int | None = None, query: str | None = None, document_id: UUID | None = None) -> None:
    request.state.audit_metadata = {"action": action, "result_count": result_count,
                                    "query": query, "document_id": document_id}


@router.get("/whoami")
def whoami(request: Request, principal: Principal = Depends(guarded(SCOPE_SEARCH, "meta"))) -> dict[str, object]:
    return {"organization_id": str(principal.organization_id), "scopes": sorted(principal.scopes),
            "restricted_to_nodes": [str(n) for n in principal.node_ids] if principal.node_ids else None}


@router.get("/sources")
def sources(request: Request, principal: Principal = Depends(guarded(SCOPE_SEARCH, "sources")),
            session: Session = Depends(database_session)) -> dict[str, object]:
    contexts = LibraryService(session).question_contexts(scope=principal.scope, user_id=principal.user_id)
    if principal.node_ids:
        try:
            selection = ScopedAccess(session, principal).selection(None)
        except SyncAccessDenied as error:
            raise HTTPException(404, "not found") from error
        folders = set(session.scalars(select(Document.workspace_folder_id).where(
            Document.organization_id == principal.organization_id,
            Document.id.in_(selection.document_ids or [])
        ))) if selection else set()
        contexts = [context for context in contexts if context.id in folders]
    _record(request, principal, "list_sources", "ok", 200, result_count=len(contexts))
    return {"sources": [{"id": str(c.id), "name": c.name, "provider": c.source_provider, "status": c.query_status}
                        for c in contexts]}


@router.post("/search")
def search(payload: SearchInput, request: Request,
           principal: Principal = Depends(guarded(SCOPE_SEARCH, "search")),
           session: Session = Depends(database_session)) -> dict[str, object]:
    try:
        selection = ScopedAccess(session, principal).selection(payload.node_ids)
    except SyncAccessDenied as error:
        _record(request, principal, "search", "denied", 404, query=payload.query)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found") from error
    hits = RetrievalService(session).search(scope=principal.scope, user_id=principal.user_id,
                                            query=payload.query, selection=selection, limit=payload.limit)
    _record(request, principal, "search", "ok", 200, result_count=len(hits), query=payload.query)
    return {"content_trust": "untrusted_document_content", "notice": UNTRUSTED_NOTICE, "results": [{"id": str(h.document_id), "title": h.title, "url": h.url, "snippet": h.snippet,
                         "page_number": h.page_number, "source_provider": h.source_provider} for h in hits]}


@router.get("/documents/{document_id}")
def document(document_id: UUID, request: Request,
             principal: Principal = Depends(guarded(SCOPE_DOCUMENTS, "documents")),
             session: Session = Depends(database_session)) -> dict[str, object]:
    try:
        selection = ScopedAccess(session, principal).selection(None)
    except SyncAccessDenied:
        selection = None
    fetched = RetrievalService(session).fetch(scope=principal.scope, user_id=principal.user_id,
                                              document_id=document_id, selection=selection)
    if fetched is None:  # foreign, out-of-scope and nonexistent documents are indistinguishable
        _record(request, principal, "fetch", "denied", 404, document_id=document_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    _record(request, principal, "fetch", "ok", 200, result_count=1, document_id=document_id)
    return {"id": str(fetched.document_id), "title": fetched.title, "url": fetched.url, "text": fetched.text,
            "content_trust": "untrusted_document_content", "notice": UNTRUSTED_NOTICE,
            "metadata": {"source_provider": fetched.source_provider, "mime_type": fetched.mime_type,
                         "modified_at": fetched.modified_at.isoformat() if fetched.modified_at else None,
                         "truncated": fetched.truncated}}


@router.post("/ask")
def ask(payload: AskInput, request: Request,
        principal: Principal = Depends(guarded(SCOPE_ASK, "ask", cap="ask")),
        session: Session = Depends(database_session)) -> dict[str, object]:
    access, settings = ScopedAccess(session, principal), request.app.state.settings
    if not settings.public_api_ask_enabled:
        raise HTTPException(503, "ask is disabled")
    provider = request.app.state.semantic_provider
    try:
        mentions = access.mentions(payload.node_ids)
        providers = access.providers()
        if settings.agent_tools_enabled:
            result, _tools, _refs = agent_service_from_settings(session, provider, settings).ask(
                scope=principal.scope, user_id=principal.user_id, question=payload.question,
                providers=providers, mentions=mentions, history=[])
        else:
            result = QuestionService(session, provider).ask_selection(
                scope=principal.scope, user_id=principal.user_id, question=payload.question,
                providers=providers, mentions=mentions)
    except (SyncAccessDenied, GoogleAccessDenied) as error:
        _record(request, principal, "ask", "denied", 403, query=payload.question)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed") from error
    except UsageLimitExceeded as error:
        session.rollback()
        _record(request, principal, "ask", "rate_limited", 429, query=payload.question)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "organization usage limit reached") from error
    except AIProviderUnavailable as error:
        session.commit()  # the question quota is recorded before the provider call (ingestion.py:423-426)
        _record(request, principal, "ask", "error", 503, query=payload.question)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI provider unavailable") from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    body = serialize_question_result(result, include_provider=True)
    if principal.node_ids:
        body.pop("coverage", None)
        body.pop("resolved_context", None)
    body.update(content_trust="untrusted_document_content", notice=UNTRUSTED_NOTICE)
    _record(request, principal, "ask", "ok", 200, result_count=len(result.citations), query=payload.question)
    return body
