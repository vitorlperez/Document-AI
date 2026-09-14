from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.google_drive import GoogleAccessDenied
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.search import MAX_PAGE_SIZE, SearchUnavailable, TextSearchService
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_context(session: Session) -> tuple[Organization, User, WorkspaceFolder]:
    organization = Organization(name="Acme")
    member = User(email=f"member-{uuid4()}@example.test")
    session.add_all([organization, member])
    session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            user_id=member.id,
            role=MembershipRole.MEMBER,
            is_active=True,
        )
    )
    source = DataSource(
        organization_id=organization.id,
        provider="google_drive",
        encrypted_credentials="ciphertext",
        status="connected",
        connected_by_user_id=member.id,
    )
    session.add(source)
    session.flush()
    folder = WorkspaceFolder(
        organization_id=organization.id,
        source_id=source.id,
        external_folder_id=f"folder-{uuid4()}",
        name="Client A",
        uniform_access_confirmed=True,
        status="ready",
    )
    session.add(folder)
    session.commit()
    return organization, member, folder


def add_document(
    session: Session,
    *,
    organization_id,
    folder_id,
    external_file_id: str,
    name: str,
    text: str,
    status: str = "indexed",
) -> Document:
    document = Document(
        organization_id=organization_id,
        workspace_folder_id=folder_id,
        external_file_id=external_file_id,
        name=name,
        mime_type="application/pdf",
        source_url=f"https://drive.example.test/{external_file_id}",
        content_hash="a" * 64,
        processing_version="v1",
        index_status=status,
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentChunk(
            organization_id=organization_id,
            workspace_folder_id=folder_id,
            document_id=document.id,
            position=0,
            text=text,
            search_text=f"{name}\n{text}",
        )
    )
    session.commit()
    return document


def search(service: TextSearchService, organization: Organization, member: User, folder: WorkspaceFolder, query: str, **kwargs):
    return service.search(
        scope=OrganizationScope(organization.id),
        user_id=member.id,
        workspace_folder_id=folder.id,
        query=query,
        **kwargs,
    )


def test_member_searches_matching_document_title_or_chunk_within_one_folder(session: Session) -> None:
    organization, member, folder = create_context(session)
    add_document(
        session,
        organization_id=organization.id,
        folder_id=folder.id,
        external_file_id="title-match",
        name="Campaign Briefing.pdf",
        text="This body uses different language.",
    )
    add_document(
        session,
        organization_id=organization.id,
        folder_id=folder.id,
        external_file_id="chunk-match",
        name="Scope.pdf",
        text="The campaign launches in September.",
    )
    service = TextSearchService(session)

    title_result = search(service, organization, member, folder, "briefing")
    chunk_result = search(service, organization, member, folder, "September")

    assert [hit.document_name for hit in title_result.items] == ["Campaign Briefing.pdf"]
    assert [hit.document_name for hit in chunk_result.items] == ["Scope.pdf"]
    assert "September" in chunk_result.items[0].excerpt


def test_search_isolated_by_folder_and_organization_and_requires_membership(session: Session) -> None:
    organization, member, first_folder = create_context(session)
    source_id = first_folder.source_id
    second_folder = WorkspaceFolder(
        organization_id=organization.id,
        source_id=source_id,
        external_folder_id="second-folder",
        name="Other client",
        uniform_access_confirmed=True,
        status="ready",
    )
    session.add(second_folder)
    session.flush()
    add_document(
        session,
        organization_id=organization.id,
        folder_id=first_folder.id,
        external_file_id="first",
        name="First.pdf",
        text="Shared search phrase",
    )
    add_document(
        session,
        organization_id=organization.id,
        folder_id=second_folder.id,
        external_file_id="second",
        name="Second.pdf",
        text="Shared search phrase",
    )
    other_organization, outsider, other_folder = create_context(session)
    add_document(
        session,
        organization_id=other_organization.id,
        folder_id=other_folder.id,
        external_file_id="foreign",
        name="Foreign.pdf",
        text="Shared search phrase",
    )
    service = TextSearchService(session)

    result = search(service, organization, member, first_folder, "shared")

    assert [hit.document_name for hit in result.items] == ["First.pdf"]
    with pytest.raises(GoogleAccessDenied):
        search(service, other_organization, outsider, first_folder, "shared")


def test_inactive_member_cannot_search_their_former_organization(session: Session) -> None:
    organization, member, folder = create_context(session)
    membership = session.query(Membership).filter_by(organization_id=organization.id, user_id=member.id).one()
    membership.is_active = False
    session.commit()

    with pytest.raises(GoogleAccessDenied):
        search(TextSearchService(session), organization, member, folder, "needle")


def test_search_omits_removed_failed_and_ignored_documents(session: Session) -> None:
    organization, member, folder = create_context(session)
    for status in ("indexed", "removed", "failed", "ignored"):
        add_document(
            session,
            organization_id=organization.id,
            folder_id=folder.id,
            external_file_id=status,
            name=f"{status}.pdf",
            text="Needle evidence",
            status=status,
        )

    result = search(TextSearchService(session), organization, member, folder, "needle")

    assert [hit.document_name for hit in result.items] == ["indexed.pdf"]


@pytest.mark.parametrize("query", ["", "  \t\n ", "x" * 501])
def test_search_rejects_blank_or_overlong_query_before_retrieval(session: Session, query: str) -> None:
    organization, member, folder = create_context(session)

    with pytest.raises(ValueError, match="query must contain"):
        search(TextSearchService(session), organization, member, folder, query)


def test_search_pagination_is_deterministic_and_capped_at_fifty(session: Session) -> None:
    organization, member, folder = create_context(session)
    for name in ("Charlie.pdf", "Alpha.pdf", "Bravo.pdf"):
        add_document(
            session,
            organization_id=organization.id,
            folder_id=folder.id,
            external_file_id=name,
            name=name,
            text="needle",
        )
    service = TextSearchService(session)

    first_page = search(service, organization, member, folder, "needle", page=1, page_size=2)
    second_page = search(service, organization, member, folder, "needle", page=2, page_size=2)

    assert [hit.document_name for hit in first_page.items] == ["Alpha.pdf", "Bravo.pdf"]
    assert [hit.document_name for hit in second_page.items] == ["Charlie.pdf"]
    assert (first_page.total, first_page.pages) == (3, 2)
    with pytest.raises(ValueError, match="invalid pagination"):
        search(service, organization, member, folder, "needle", page_size=MAX_PAGE_SIZE + 1)


def test_search_requires_ready_or_partial_failure_folder(session: Session) -> None:
    organization, member, folder = create_context(session)
    folder.status = "queued"
    session.commit()

    with pytest.raises(SearchUnavailable):
        search(TextSearchService(session), organization, member, folder, "needle")
