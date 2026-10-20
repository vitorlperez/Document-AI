"""Unified content search over every Space the caller belongs to (ADR-0021 T-E4)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.presentation import short_citation_excerpt
from app.knowledge.retrieval import MAX_SEARCH_LIMIT, RetrievalService
from app.knowledge.space_seals import spaces_payload
from app.knowledge.untrusted import UNTRUSTED_NOTICE, safe_label, strip_invisible
from app.library.service import LibraryService
from app.spaces.access import SpaceAccessResolver
from app.spaces.filter import narrowed_to_spaces
from app.spaces.service import SpaceNotFound

router = APIRouter(tags=["search"])
ALL_PROVIDERS = ["google_drive", "notion", "onedrive", "sharepoint", "clickup"]


class OrganizationSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=MAX_SEARCH_LIMIT)
    space_ids: list[UUID] | None = Field(default=None, max_length=50)


@router.post("/organizations/{organization_id}/search")
def search_organization(
    organization_id: UUID, payload: OrganizationSearchInput, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    scope = OrganizationScope(organization_id)
    try:
        if payload.space_ids:  # a Space that is not the caller's does not exist for them
            SpaceAccessResolver(session).resolve(scope=scope, user_id=user.id, space_ids=payload.space_ids, strict=True)
        with narrowed_to_spaces(payload.space_ids):
            selection = LibraryService(session).resolve_question_selection(
                scope=scope, user_id=user.id, providers=ALL_PROVIDERS, mentions=[])
            hits = RetrievalService(session).search(
                scope=scope, user_id=user.id, query=payload.query, selection=selection, limit=payload.limit)
    except SpaceNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "space not found") from error
    except SyncAccessDenied as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed") from error
    return {
        "results": [{
            "document_id": str(hit.document_id), "title": safe_label(hit.title), "url": hit.url,
            "snippet": short_citation_excerpt(strip_invisible(hit.snippet)), "page_number": hit.page_number,
            "score": hit.score, "source_provider": hit.source_provider, "spaces": spaces_payload(hit.spaces),
        } for hit in hits],
        "metadata": {"content_trust": "untrusted_document_content", "notice": UNTRUSTED_NOTICE},
    }
