import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveredDocument, IngestionService, SyncAccessDenied
from app.integrations.google_drive import RemoteFolder
from app.integrations.models import DataSource
from app.knowledge.models import Document
from app.library.models import LibraryExclusion, LibraryNode
from app.library.service import LibraryService
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_company(session: Session, *, email: str = "member@example.test") -> tuple[Organization, User, DataSource]:
    user, organization = User(email=email), Organization(name="Acme")
    session.add_all([user, organization])
    session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.MEMBER, is_active=True))
    source = DataSource(
        organization_id=organization.id,
        provider="google_drive",
        encrypted_credentials="encrypted",
        status="connected",
        connected_by_user_id=user.id,
    )
    session.add(source)
    session.flush()
    return organization, user, source


def seed_document(session: Session, *, organization: Organization, source: DataSource, root: str, external_id: str, name: str, status: str = "indexed") -> WorkspaceFolder:
    workspace = WorkspaceFolder(
        organization_id=organization.id,
        source_id=source.id,
        external_folder_id=root,
        name=root,
        uniform_access_confirmed=True,
        status="ready",
    )
    session.add(workspace)
    session.flush()
    session.add(Document(
        organization_id=organization.id,
        workspace_folder_id=workspace.id,
        external_file_id=external_id,
        name=name,
        mime_type="application/pdf",
        source_url=f"https://drive.example.test/{external_id}",
        content_hash="hash",
        processing_version="v1",
        index_status=status,
    ))
    session.flush()
    return workspace


def test_projects_nested_drive_tree_and_merges_overlapping_syncs(session: Session) -> None:
    organization, user, source = seed_company(session)
    scope_a = seed_document(session, organization=organization, source=source, root="A", external_id="brief", name="Brief.pdf")
    scope_b = seed_document(session, organization=organization, source=source, root="B", external_id="brief", name="Brief.pdf")
    service = LibraryService(session)
    documents = [DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "https://drive.example.test/brief", text="content", parent_ids=("campaign",))]
    service.project_successful_sync(
        organization_id=organization.id,
        source=source,
        documents=documents,
        folders=[RemoteFolder("client", "Client"), RemoteFolder("campaign", "Campaign", ("client",))],
    )

    root = service.roots(scope=OrganizationScope(organization.id), user_id=user.id)[0]
    client = service.children(scope=OrganizationScope(organization.id), user_id=user.id, parent_id=root.id, page=1, page_size=100).items
    assert [(node.kind, node.name) for node in client] == [("folder", "Client")]
    campaign = service.children(scope=OrganizationScope(organization.id), user_id=user.id, parent_id=client[0].id, page=1, page_size=100).items[0]
    files = service.children(scope=OrganizationScope(organization.id), user_id=user.id, parent_id=campaign.id, page=1, page_size=100).items
    assert [(node.kind, node.name, node.source_url) for node in files] == [("file", "Brief.pdf", "https://drive.example.test/brief")]
    assert session.query(LibraryNode).filter_by(source_id=source.id, external_id="brief").count() == 1
    assert set(service.workspace_provenance(scope=OrganizationScope(organization.id), node=files[0])) == {scope_a.id, scope_b.id}

    membership = session.query(Membership).filter_by(organization_id=organization.id, user_id=user.id).one()
    membership.role = MembershipRole.ADMIN
    document_a = session.query(Document).filter_by(workspace_folder_id=scope_a.id, external_file_id="brief").one()
    document_b = session.query(Document).filter_by(workspace_folder_id=scope_b.id, external_file_id="brief").one()
    ingestion = IngestionService(session)
    removed_a = ingestion.remove_indexed_document(
        scope=OrganizationScope(organization.id), user_id=user.id, workspace_folder_id=scope_a.id, document_id=document_a.id
    )
    service.remove_file_if_unindexed(
        scope=OrganizationScope(organization.id), source_id=removed_a.source_id, external_file_id=removed_a.external_file_id
    )
    assert session.query(LibraryNode).filter_by(source_id=source.id, external_id="brief").count() == 1
    remaining = service.document_provenance(scope=OrganizationScope(organization.id), node=files[0])
    assert [(item.workspace_folder_id, item.document_id) for item in remaining] == [(scope_b.id, document_b.id)]

    removed_b = ingestion.remove_indexed_document(
        scope=OrganizationScope(organization.id), user_id=user.id, workspace_folder_id=scope_b.id, document_id=document_b.id
    )
    service.remove_file_if_unindexed(
        scope=OrganizationScope(organization.id), source_id=removed_b.source_id, external_file_id=removed_b.external_file_id
    )
    assert session.query(LibraryNode).filter_by(source_id=source.id, external_id="brief").count() == 0
    assert session.query(LibraryExclusion).filter_by(source_id=source.id, external_id="brief").count() == 1


def test_projection_refreshes_remote_folder_names_and_parents(session: Session) -> None:
    organization, user, source = seed_company(session)
    seed_document(
        session,
        organization=organization,
        source=source,
        root="campaigns",
        external_id="brief",
        name="Brief.pdf",
    )
    service = LibraryService(session)
    service.project_successful_sync(
        organization_id=organization.id,
        source=source,
        documents=[
            DiscoveredDocument(
                "brief",
                "Brief.pdf",
                "application/pdf",
                "https://drive.example.test/brief",
                text="content",
                parent_ids=("campaign",),
            )
        ],
        folders=[RemoteFolder("client", "Client"), RemoteFolder("campaign", "Campaign", ("client",))],
    )

    service.project_successful_sync(
        organization_id=organization.id,
        source=source,
        documents=[],
        folders=[
            RemoteFolder("client", "Client"),
            RemoteFolder("campaign", "Campaign archive", ("root",)),
        ],
    )

    root = service.roots(scope=OrganizationScope(organization.id), user_id=user.id)[0]
    top_level = service.children(
        scope=OrganizationScope(organization.id),
        user_id=user.id,
        parent_id=root.id,
        page=1,
        page_size=100,
    ).items
    assert [(node.kind, node.name) for node in top_level] == [
        ("folder", "Campaign archive"),
        ("folder", "Client"),
    ]
    assert top_level[0].parent_id == root.id


def test_projection_removes_nodes_missing_from_complete_remote_snapshot(session: Session) -> None:
    organization, _user, source = seed_company(session)
    workspace = seed_document(session, organization=organization, source=source, root="A",
                              external_id="obsolete", name="Obsolete.pdf")
    service = LibraryService(session)
    document = DiscoveredDocument(
        "obsolete",
        "Obsolete.pdf",
        "application/pdf",
        "https://drive.example.test/obsolete",
        text="content",
    )
    service.project_successful_sync(
        organization_id=organization.id, source=source, documents=[document], folders=[],
        workspace_folder_id=workspace.id,
    )
    assert service._by_external(source_id=source.id, external_id=document.external_file_id) is not None

    # The complete snapshot no longer has it, so reconciliation marked it removed.
    session.query(Document).filter_by(external_file_id="obsolete").one().index_status = "removed"
    service.project_successful_sync(
        organization_id=organization.id, source=source, documents=[], folders=[],
        workspace_folder_id=workspace.id,
    )

    assert service._by_external(source_id=source.id, external_id=document.external_file_id) is None


def test_projection_includes_synchronized_nonindexed_files_and_isolates_organizations(session: Session) -> None:
    organization, user, source = seed_company(session)
    seed_document(session, organization=organization, source=source, root="A", external_id="ready", name="Ready.pdf")
    seed_document(session, organization=organization, source=source, root="B", external_id="failed", name="Failed.pdf", status="failed")
    service = LibraryService(session)
    service.project_successful_sync(
        organization_id=organization.id,
        source=source,
        documents=[
            DiscoveredDocument("ready", "Ready.pdf", "application/pdf", "https://drive.example.test/ready", text="content"),
            DiscoveredDocument("failed", "Failed.pdf", "application/pdf", "https://drive.example.test/failed", text="content"),
        ],
        folders=[],
    )
    root = service.roots(scope=OrganizationScope(organization.id), user_id=user.id)[0]
    assert [
        node.name
        for node in service.children(
            scope=OrganizationScope(organization.id),
            user_id=user.id,
            parent_id=root.id,
            page=1,
            page_size=100,
        ).items
    ] == ["Failed.pdf", "Ready.pdf"]

    other_org, other_user, _ = seed_company(session, email="other@example.test")
    with pytest.raises(SyncAccessDenied):
        service.roots(scope=OrganizationScope(organization.id), user_id=other_user.id)
    with pytest.raises(SyncAccessDenied):
        service.children(scope=OrganizationScope(other_org.id), user_id=other_user.id, parent_id=root.id, page=1, page_size=100)


def test_children_are_bounded_and_stably_paged(session: Session) -> None:
    organization, user, source = seed_company(session)
    service = LibraryService(session)
    root = service._root(organization_id=organization.id, source=source)
    for index in range(101):
        session.add(LibraryNode(organization_id=organization.id, source_id=source.id, parent_id=root.id, external_id=f"file-{index}", kind="file", name=f"File {index:03d}", mime_type="application/pdf", source_url=None))
    session.flush()
    first = service.children(scope=OrganizationScope(organization.id), user_id=user.id, parent_id=root.id, page=1, page_size=100)
    second = service.children(scope=OrganizationScope(organization.id), user_id=user.id, parent_id=root.id, page=2, page_size=100)
    assert first.total == 101 and len(first.items) == 100 and len(second.items) == 1
    assert {item.id for item in first.items}.isdisjoint({item.id for item in second.items})


def test_empty_folder_pruning_uses_bounded_queries(session: Session) -> None:
    organization, _, source = seed_company(session)
    service = LibraryService(session)
    root = service._root(organization_id=organization.id, source=source)
    for index in range(20):
        session.add(LibraryNode(
            organization_id=organization.id, source_id=source.id, parent_id=root.id,
            external_id=f"empty-{index}", kind="folder", name=f"Empty {index}",
            mime_type=None, source_url=None,
        ))
    session.flush()
    statements: list[str] = []

    def count_reads(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().startswith("SELECT") and "FROM library_nodes" in statement:
            statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", count_reads)
    try:
        service._remove_empty_folders(source_id=source.id)
    finally:
        event.remove(session.bind, "before_cursor_execute", count_reads)
    assert session.query(LibraryNode).filter_by(source_id=source.id).count() == 1
    assert len(statements) <= 4


def test_library_metadata_search_and_sync_statuses_are_member_scoped(session: Session) -> None:
    organization, user, source = seed_company(session)
    workspace = seed_document(session, organization=organization, source=source, root="campaigns", external_id="brief", name="Campaign Brief.pdf")
    service = LibraryService(session)
    root = service._root(organization_id=organization.id, source=source)
    folder = LibraryNode(organization_id=organization.id, source_id=source.id, parent_id=root.id, external_id="campaigns", kind="folder", name="Campaigns", mime_type=None, source_url=None)
    session.add(folder)
    session.flush()
    result = service.search_names(scope=OrganizationScope(organization.id), user_id=user.id, query=" campaign ")
    assert [(item.kind, item.name) for item in result] == [("folder", "Campaigns")]
    with pytest.raises(ValueError):
        service.search_names(scope=OrganizationScope(organization.id), user_id=user.id, query="   ")

    session.add_all([
        ProcessingJob(organization_id=organization.id, workspace_folder_id=workspace.id, idempotency_key="syncing", status=ProcessingJobStatus.SYNCING),
        ProcessingJob(organization_id=organization.id, workspace_folder_id=workspace.id, idempotency_key="ready", status=ProcessingJobStatus.READY),
    ])
    session.flush()
    syncs = service.recent_syncs(scope=OrganizationScope(organization.id), user_id=user.id)
    assert [item.status for item in syncs] == ["syncing", "ready"]
    contexts = service.question_contexts(scope=OrganizationScope(organization.id), user_id=user.id)
    assert [item.id for item in contexts] == [workspace.id]
    assert [item.query_status for item in contexts] == ["no_indexed_content"]


def test_projection_of_a_second_sync_keeps_or_drops_nodes_of_other_workspace(session):
    organization, _, source = seed_company(session)
    source.provider = "onedrive"
    seed_document(session, organization=organization, source=source, root="A", external_id="a1", name="A.pdf")
    seed_document(session, organization=organization, source=source, root="B", external_id="b1", name="B.pdf")
    service = LibraryService(session)
    workspaces = {item.external_file_id: item.workspace_folder_id for item in session.query(Document)}
    for external_id in ("a1", "b1"):
        service.project_successful_sync(
            organization_id=organization.id, source=source,
            documents=[DiscoveredDocument(external_id, external_id + ".pdf", "application/pdf", "", text="content")],
            folders=[], workspace_folder_id=workspaces[external_id],
        )
    # The catalog is shared by every space of the source: syncing B keeps A.
    assert service._by_external(source_id=source.id, external_id="a1") is not None
    assert service._by_external(source_id=source.id, external_id="b1") is not None
