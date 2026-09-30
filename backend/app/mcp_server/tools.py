"""Read-only MCP tools. Scope comes only from the Principal; arguments carry no tenant/URL selectors."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.principal import Principal
from app.access.scope import ScopedAccess
from app.ingestion.service import SyncAccessDenied
from app.knowledge.models import Document
from app.knowledge.retrieval import RetrievalService
from app.knowledge.untrusted import UNTRUSTED_NOTICE, strip_invisible
from app.library.service import LibraryService

MCP_TOOL_NAMES = ("search", "fetch", "list_sources")
TITLE_CHARS = 300
SEARCH_LIMIT = 10


class ToolNotFound(Exception):
    """Foreign, out-of-scope, malformed and nonexistent ids are indistinguishable."""


def _selection(session: Session, principal: Principal):
    try:
        return ScopedAccess(session, principal).selection(None)
    except SyncAccessDenied:
        return None


def run_search(session: Session, principal: Principal, query: str) -> dict[str, object]:
    principal.require("search:read")
    hits = RetrievalService(session).search(
        scope=principal.scope, user_id=principal.user_id, query=query[:500],
        selection=_selection(session, principal), limit=SEARCH_LIMIT,
    )
    return {"results": [
        {"id": str(hit.document_id), "title": strip_invisible(hit.title)[:TITLE_CHARS], "url": hit.url,
         "text": hit.snippet}
        for hit in hits
    ]}


def run_fetch(session: Session, principal: Principal, id: str) -> dict[str, object]:
    principal.require("documents:read")
    try:
        document_id = UUID(id)
    except (ValueError, AttributeError, TypeError) as error:
        raise ToolNotFound from error
    fetched = RetrievalService(session).fetch(
        scope=principal.scope, user_id=principal.user_id, document_id=document_id,
        selection=_selection(session, principal),
    )
    if fetched is None:
        raise ToolNotFound
    return {
        "id": str(fetched.document_id), "title": strip_invisible(fetched.title)[:TITLE_CHARS], "text": fetched.text,
        "url": fetched.url,
        "metadata": {
            "content_trust": "untrusted_document_content", "notice": UNTRUSTED_NOTICE,
            "source_provider": fetched.source_provider, "mime_type": fetched.mime_type,
            "modified_at": fetched.modified_at.isoformat() if fetched.modified_at else None,
            "truncated": fetched.truncated,
        },
    }


def run_list_sources(session: Session, principal: Principal) -> dict[str, object]:
    principal.require("search:read")
    contexts = LibraryService(session).question_contexts(scope=principal.scope, user_id=principal.user_id)
    if principal.node_ids:
        selection = _selection(session, principal)
        folders = set(session.scalars(select(Document.workspace_folder_id).where(
            Document.organization_id == principal.organization_id,
            Document.id.in_(selection.document_ids or []),
        ))) if selection else set()
        contexts = [context for context in contexts if context.id in folders]
    return {"sources": [
        {"id": str(c.id), "name": strip_invisible(c.name)[:TITLE_CHARS], "provider": c.source_provider,
         "status": c.query_status}
        for c in contexts
    ]}
