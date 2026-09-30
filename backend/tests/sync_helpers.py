"""Shared fixtures for the sync/resync invariant regressions (M25)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import DiscoveredDocument, DiscoveryResult, IngestionService
from app.integrations.google_drive import RemoteFolder
from app.integrations.models import DataSource
from app.knowledge.models import Document
from app.library.models import LibraryExclusion
from app.library.service import LibraryService
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

T0 = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed(session: Session):
    organization, user = Organization(name="Acme"), User(email="admin@example.test")
    session.add_all([organization, user])
    session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id,
                           role=MembershipRole.ADMIN, is_active=True))
    source = DataSource(organization_id=organization.id, provider="google_drive",
                        encrypted_credentials="ciphertext", status="connected",
                        connected_by_user_id=user.id)
    session.add(source)
    session.flush()
    return organization, user, source


def space(session: Session, organization, source, key: str, *, created_at: datetime,
          folder_id: str | None = None) -> WorkspaceFolder:
    folder = WorkspaceFolder(organization_id=organization.id, source_id=source.id,
                             external_folder_id=f"scope:{key}", name=key,
                             uniform_access_confirmed=True, created_at=created_at)
    session.add(folder)
    session.flush()
    session.add(WorkspaceFolderSelection(
        workspace_folder_id=folder.id,
        kind="folder" if folder_id else "all_accessible",
        external_folder_id=folder_id or "",
    ))
    session.flush()
    return folder


def exclude(session: Session, organization, source, external_id: str, kind: str, *, at: datetime) -> None:
    session.add(LibraryExclusion(organization_id=organization.id, source_id=source.id,
                                 external_id=external_id, kind=kind, created_at=at))
    session.flush()


def doc(external_id: str, *, parent: str = "tda", text: str = "conteúdo") -> DiscoveredDocument:
    return DiscoveredDocument(external_id, f"{external_id}.pdf", "application/pdf", "", text=text,
                              parent_ids=(parent,))


TREE = [RemoteFolder("tda", "Test Document-AI"), RemoteFolder("sub", "Sub", ("tda",))]


def sync(session: Session, organization, user, folder, documents, *, full_snapshot=True, folders=TREE):
    service = IngestionService(session)
    job = service.enqueue(scope=OrganizationScope(organization.id), user_id=user.id,
                          workspace_folder_id=folder.id)
    job = service.claim(job_id=job.id)
    service.apply_reconciliation(
        job_id=job.id, run_token=job.run_token,
        documents=DiscoveryResult(documents=documents, full_snapshot=full_snapshot),
        manual_folders=folders,
    )
    LibraryService(session).project_successful_sync(
        organization_id=organization.id, source=session.get(DataSource, folder.source_id),
        documents=documents, folders=folders, workspace_folder_id=folder.id,
    )
    session.flush()
    return job


def statuses(session: Session, folder) -> dict[str, str]:
    return {item.external_file_id: item.index_status for item in session.scalars(
        select(Document).where(Document.workspace_folder_id == folder.id))}


