"""Folder-scoped textual retrieval with a PostgreSQL FTS fast path."""

from dataclasses import dataclass
from math import ceil
from uuid import UUID

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.knowledge.models import Document, DocumentChunk
from app.workspaces.service import WorkspaceService

MAX_PAGE_SIZE = 50
MAX_QUERY_LENGTH = 500


@dataclass(frozen=True)
class TextSearchHit:
    document_id: UUID
    document_name: str
    excerpt: str
    page_number: int | None
    source_url: str


@dataclass(frozen=True)
class TextSearchPage:
    items: list[TextSearchHit]
    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        return ceil(self.total / self.page_size) if self.total else 0


class SearchUnavailable(RuntimeError):
    pass


class TextSearchService:
    def __init__(self, session: Session):
        self.session = session

    def search(
        self,
        *,
        scope: OrganizationScope,
        user_id: UUID,
        workspace_folder_id: UUID,
        query: str,
        page: int = 1,
        page_size: int = 20,
    ) -> TextSearchPage:
        normalized_query = _validate_query(query)
        if not 1 <= page_size <= MAX_PAGE_SIZE or page < 1:
            raise ValueError("invalid pagination")
        folder = WorkspaceService(self.session).require_member_access(
            scope=scope, user_id=user_id, workspace_folder_id=workspace_folder_id
        )
        if folder.status not in {"ready", "partial_failure"}:
            raise SearchUnavailable("workspace folder is not searchable")

        filters = [
            Document.organization_id == scope.organization_id,
            Document.workspace_folder_id == workspace_folder_id,
            Document.index_status == "indexed",
            DocumentChunk.organization_id == scope.organization_id,
            DocumentChunk.workspace_folder_id == workspace_folder_id,
        ]
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            tsquery = func.websearch_to_tsquery("simple", normalized_query)
            search_vector = literal_column("document_chunks.search_vector")
            match = search_vector.op("@@")(tsquery)
            rank = func.ts_rank_cd(search_vector, tsquery)
            filters.append(match)
            ordering = (rank.desc(), Document.name, Document.id, DocumentChunk.position)
        else:
            # This compatibility path is limited to local SQLite tests. Production
            # PostgreSQL uses the stored GIN-indexed vector above.
            terms = [term for term in normalized_query.lower().split() if term]
            match = or_(*(func.lower(DocumentChunk.search_text).contains(term) for term in terms))
            filters.append(match)
            ordering = (Document.name, Document.id, DocumentChunk.position)

        base = select(Document, DocumentChunk).join(DocumentChunk, DocumentChunk.document_id == Document.id).where(*filters)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.execute(
            base.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return TextSearchPage(
            items=[
                TextSearchHit(
                    document_id=document.id,
                    document_name=document.name,
                    excerpt=_excerpt(chunk.text, normalized_query),
                    page_number=chunk.page_number,
                    source_url=document.source_url,
                )
                for document, chunk in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )


def _validate_query(query: str) -> str:
    normalized = " ".join(query.split())
    if not normalized or len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError("query must contain between 1 and 500 characters")
    return normalized


def _excerpt(text: str, query: str, *, limit: int = 320) -> str:
    lowered = text.lower()
    first_term = query.lower().split()[0]
    start = max(0, lowered.find(first_term) - 80)
    excerpt = text[start : start + limit].strip()
    return f"…{excerpt}" if start else excerpt
