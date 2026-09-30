"""Persist call metadata in an independent transaction; never persist request content."""
import hashlib
import logging
from uuid import UUID

from app.access.models import ApiAuditEvent
from app.access.principal import Principal

logger = logging.getLogger(__name__)


class AuditWriter:
    def __init__(self, session_factory):
        self._factory = session_factory

    def record(
        self, *, principal: Principal | None, organization_id: UUID | None, channel: str,
        action: str, status: str, http_status: int | None, request_id: str | None,
        latency_ms: int | None, result_count: int | None = None, query: str | None = None,
        document_id: UUID | None = None,
    ) -> None:
        organization_id = principal.organization_id if principal else organization_id
        if organization_id is None:
            return
        try:
            with self._factory.begin() as session:
                session.add(ApiAuditEvent(
                    organization_id=organization_id, channel=channel,
                    credential_id=principal.credential_id if principal else None,
                    user_id=principal.user_id if principal else None,
                    action=action, status=status, http_status=http_status,
                    request_id=request_id[:64] if request_id else None, latency_ms=latency_ms,
                    result_count=result_count, document_id=document_id,
                    query_sha256=hashlib.sha256(query.encode()).hexdigest() if query else None,
                    query_length=len(query) if query is not None else None,
                ))
        except Exception:  # noqa: BLE001 — fail open without logging SQL parameters
            # Exception messages can contain SQL parameters: emit only a fixed message.
            logger.error("audit write failed", extra={"event": "api_audit_failed"})
