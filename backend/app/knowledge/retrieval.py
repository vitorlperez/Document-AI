"""Evidence retrieval without generation, always tenant/member scoped (search and fetch tools)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import join_overlapping_text, query_terms
from app.knowledge.search import _excerpt
from app.knowledge.untrusted import strip_invisible
from app.library.service import LibraryService, QuestionSelection
from app.workspaces.models import WorkspaceFolder

MAX_FETCH_CHARS = 100_000  # Claude tolerates ~150k characters per tool result
MAX_SEARCH_LIMIT = 20
SNIPPET_CHARS = 400


@dataclass(frozen=True)
class SearchHit:
    document_id: UUID
    title: str
    url: str
    snippet: str
    page_number: int | None
    score: float
    source_provider: str | None


@dataclass(frozen=True)
class FetchedDocument:
    document_id: UUID
    title: str
    url: str
    text: str
    source_provider: str | None
    mime_type: str
    modified_at: datetime | None
    truncated: bool


class RetrievalService:
    def __init__(self, session: Session):
        self.session = session

    def _scoped(self, scope: OrganizationScope, selection: QuestionSelection):
        filters = [
            Document.organization_id == scope.organization_id,
            Document.workspace_folder_id.in_(selection.folder_ids),
            Document.index_status == "indexed",
            DocumentChunk.organization_id == scope.organization_id,
            DocumentChunk.workspace_folder_id.in_(selection.folder_ids),
            DocumentChunk.workspace_folder_id == Document.workspace_folder_id,
        ]
        if selection.document_ids is not None:
            filters.append(Document.id.in_(selection.document_ids))
        return filters

    def search(
        self, *, scope: OrganizationScope, user_id: UUID, query: str, selection: QuestionSelection | None,
        limit: int = 10,
    ) -> list[SearchHit]:
        LibraryService(self.session).require_member(scope=scope, user_id=user_id)
        terms = sorted(query_terms(query))  # alphanumeric tokens only: safe to join into a tsquery
        if not terms or selection is None or not selection.folder_ids:
            return []
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        filters = self._scoped(scope, selection)
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            tsquery = func.to_tsquery("simple", " | ".join(terms))
            vector = literal_column("document_chunks.search_vector")
            rank = func.ts_rank_cd(vector, tsquery)
            filters.append(vector.op("@@")(tsquery))
        else:  # SQLite test path, same as search.py:74-80
            rank = func.length(DocumentChunk.text) * 0 + 1.0
            filters.append(or_(*(func.lower(DocumentChunk.search_text).contains(t) for t in terms)))
        rows = self.session.execute(
            select(Document, DocumentChunk, rank.label("score"), DataSource.provider)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
            .where(*filters, DataSource.organization_id == scope.organization_id)
            .order_by(rank.desc(), Document.name, Document.id, DocumentChunk.position)
            .limit(limit * 5)
        ).all()
        best: dict[UUID, SearchHit] = {}
        for document, chunk, score, provider in rows:
            if document.id in best:
                continue
            best[document.id] = SearchHit(
                document_id=document.id, title=document.name, url=document.source_url,
                snippet=strip_invisible(_excerpt(chunk.text, " ".join(terms), limit=SNIPPET_CHARS)),
                page_number=chunk.page_number, score=float(score), source_provider=provider,
            )
        return list(best.values())[:limit]

    def fetch(
        self, *, scope: OrganizationScope, user_id: UUID, document_id: UUID,
        selection: QuestionSelection | None, max_chars: int = MAX_FETCH_CHARS,
    ) -> FetchedDocument | None:
        LibraryService(self.session).require_member(scope=scope, user_id=user_id)
        if selection is None or (selection.document_ids is not None and document_id not in selection.document_ids):
            return None
        row = self.session.execute(
            select(Document, DataSource.provider)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
            .where(
                Document.id == document_id, Document.organization_id == scope.organization_id,
                Document.workspace_folder_id.in_(selection.folder_ids), Document.index_status == "indexed",
                DataSource.organization_id == scope.organization_id,
            )
        ).first()
        if row is None:
            return None
        document, provider = row
        text = ""
        for chunk_text in self.session.scalars(
            select(DocumentChunk.text)
            .where(DocumentChunk.document_id == document.id, DocumentChunk.organization_id == scope.organization_id)
            .order_by(DocumentChunk.position)
        ):
            text = join_overlapping_text(text, chunk_text) if text else chunk_text
            if len(text) > max_chars:
                break
        clean = strip_invisible(text)
        return FetchedDocument(
            document_id=document.id, title=document.name, url=document.source_url, text=clean[:max_chars],
            source_provider=provider, mime_type=document.mime_type, modified_at=document.modified_at,
            truncated=len(clean) > max_chars,
        )
