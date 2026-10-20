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
from app.spaces.service import SpaceNotFound

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


def _space_ids(raw: list[str] | None) -> list[UUID] | None:
    try:
        return [UUID(item) for item in raw] if raw else None
    except (ValueError, AttributeError, TypeError) as error:
        raise ToolNotFound from error


def _spaces(refs) -> list[dict[str, str]]:
    return [{"id": str(ref.id), "name": strip_invisible(ref.name)[:TITLE_CHARS]} for ref in refs]


def run_search(session: Session, principal: Principal, query: str, space_ids: list[str] | None = None) -> dict[str, object]:
    principal.require("search:read")
    access = ScopedAccess(session, principal)
    try:
        with access.narrowed(_space_ids(space_ids)):  # a Space that is not the user's does not exist
            hits = RetrievalService(session).search(
                scope=principal.scope, user_id=principal.user_id, query=query[:500],
                selection=_selection(session, principal), limit=SEARCH_LIMIT,
            )
    except SpaceNotFound as error:
        raise ToolNotFound from error
    return {"results": [
        {"id": str(hit.document_id), "title": strip_invisible(hit.title)[:TITLE_CHARS], "url": hit.url,
         "text": strip_invisible(hit.snippet), "spaces": _spaces(hit.spaces)}
        for hit in hits
    ], "metadata": {"content_trust": "untrusted_document_content", "notice": UNTRUSTED_NOTICE}}


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
         "status": c.query_status, "spaces": _spaces(c.spaces)}
        for c in contexts
    ]}
