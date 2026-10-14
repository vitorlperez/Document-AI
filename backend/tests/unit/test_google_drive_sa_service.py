from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.google_drive_sa import FolderAccessLost, SaRequestError
from app.integrations.google_drive_sa_service import DriveSaConnectionService
from app.integrations.google_sa_models import DriveFolderLink, GoogleSaIdentity, GoogleSaProject
from app.knowledge.models import Document, DocumentChunk
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder


class FakeClient:
    def __init__(self):
        self.allowed = True

    def verify_folder(self, **kwargs):
        if not self.allowed:
            raise FolderAccessLost(kwargs["folder_id"])
        root = {
            "id": kwargs["folder_id"],
            "name": "Contracts",
            "mimeType": "application/vnd.google-apps.folder",
            "sharedWithMeTime": "2026-10-14T00:00:00Z",
        }
        return root, root

    def list_folder_files(self, **kwargs):
        return []


@pytest.fixture
def setup():
    # Import all product models using the same bootstrap as API tests.
    import app.automations.models, app.access.models, app.notifications.models, app.library.models  # noqa

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(email="owner@example.test")
        orgs = [Organization(name="A"), Organization(name="B")]
        session.add_all([user, *orgs])
        session.flush()
        for org in orgs:
            session.add(
                Membership(
                    organization_id=org.id,
                    user_id=user.id,
                    role=MembershipRole.OWNER,
                    is_active=True,
                )
            )
        project = GoogleSaProject(gcp_project_id="pool")
        session.add(project)
        session.flush()
        for n in range(2):
            session.add(
                GoogleSaIdentity(
                    project_id=project.id,
                    sa_email=f"robot{n}@example.test",
                    encrypted_key="encrypted",
                )
            )
        session.commit()
        settings = Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            google_drive_sa_enabled=True,
            google_sa_key_encryption_key=Fernet.generate_key().decode(),
            _env_file=None,
        )
        client = FakeClient()
        service = DriveSaConnectionService(
            session, settings, client=client, credential_factory=lambda identity: None
        )
        yield service, session, user, orgs, client


def enable(service, user, org):
    return service.enable(scope=OrganizationScope(org.id), user_id=user.id)


def test_two_tenants_pool_assignment_and_inaccessible_folder(setup):
    service, session, user, orgs, client = setup
    a = enable(service, user, orgs[0])
    b = enable(service, user, orgs[1])
    assert a.sa_identity_id != b.sa_identity_id
    assert enable(service, user, orgs[0]).id == a.id
    with pytest.raises(SaRequestError, match="not_shared"):
        service.source(scope=OrganizationScope(orgs[1].id), user_id=user.id, source_id=a.id)
    client.allowed = False
    with pytest.raises(FolderAccessLost):
        service.link(
            scope=OrganizationScope(orgs[1].id),
            user_id=user.id,
            source_id=b.id,
            folder_id="folder_123456",
        )
    assert session.scalar(select(DriveFolderLink)) is None
    service.disconnect(scope=OrganizationScope(orgs[0].id), user_id=user.id, source_id=a.id)
    assert session.get(GoogleSaIdentity, a.sa_identity_id).status == "retired"
    with pytest.raises(SaRequestError):
        enable(service, user, orgs[0])


def test_loss_hides_without_deletion_confirm_hour_and_restore(setup):
    service, session, user, orgs, client = setup
    source = enable(service, user, orgs[0])
    scope = OrganizationScope(orgs[0].id)
    link = service.link(
        scope=scope, user_id=user.id, source_id=source.id, folder_id="folder_123456"
    )
    doc = Document(
        organization_id=scope.organization_id,
        workspace_folder_id=link.workspace_folder_id,
        external_file_id="file_123456",
        name="doc",
        mime_type="text/plain",
        source_url="url",
        content_hash="h",
        index_status="indexed",
    )
    session.add(doc)
    session.flush()
    chunk = DocumentChunk(
        organization_id=scope.organization_id,
        workspace_folder_id=link.workspace_folder_id,
        document_id=doc.id,
        position=0,
        text="secret",
        search_text="secret",
    )
    session.add(chunk)
    session.flush()
    now = datetime.now(UTC)
    client.allowed = False
    service.recheck(source, now=now)
    assert link.status == "suspect"
    assert doc.index_status == "access_lost"
    assert session.get(DocumentChunk, chunk.id).text == "secret"
    service.recheck(source, now=now + timedelta(minutes=59))
    assert link.status == "suspect"
    service.recheck(source, now=now + timedelta(hours=1))
    assert link.status == "access_lost"
    from app.integrations.google_drive_sa_service import utc

    assert utc(link.purge_after) == now + timedelta(days=14)
    client.allowed = True
    service.recheck(source, now=now + timedelta(hours=2))
    assert link.status == "verified"
    assert link.purge_after is None
    assert doc.index_status == "indexed"


def test_unlink_and_retention_purge_only_own_content(setup):
    service, session, user, orgs, _client = setup
    sources = [enable(service, user, org) for org in orgs]
    links = [
        service.link(
            scope=OrganizationScope(org.id),
            user_id=user.id,
            source_id=source.id,
            folder_id=f"folder_12345{n}",
        )
        for n, (org, source) in enumerate(zip(orgs, sources))
    ]
    docs = []
    for link in links:
        doc = Document(
            organization_id=link.organization_id,
            workspace_folder_id=link.workspace_folder_id,
            external_file_id="file_123456",
            name="doc",
            mime_type="text/plain",
            source_url="url",
            content_hash="h",
            index_status="indexed",
        )
        session.add(doc)
        docs.append(doc)
    session.flush()
    service.unlink(
        scope=OrganizationScope(orgs[0].id),
        user_id=user.id,
        source_id=sources[0].id,
        link_id=links[0].id,
        purge=True,
    )
    assert links[0].status == "removed"
    assert session.get(Document, docs[0].id) is None
    assert session.get(Document, docs[1].id) is not None
    service.unlink(
        scope=OrganizationScope(orgs[1].id),
        user_id=user.id,
        source_id=sources[1].id,
        link_id=links[1].id,
    )
    assert service.purge_due(now=datetime.now(UTC) + timedelta(days=13)) == 0
    assert service.purge_due(now=datetime.now(UTC) + timedelta(days=15)) == 1
    assert session.get(Document, docs[1].id) is None


def test_member_cannot_enable(setup):
    service, session, user, orgs, _ = setup
    membership = session.scalar(select(Membership).where(Membership.organization_id == orgs[0].id))
    membership.role = MembershipRole.MEMBER
    session.flush()
    with pytest.raises(SaRequestError, match="forbidden"):
        enable(service, user, orgs[0])


def test_disabled_maintenance_has_no_side_effects(setup):
    from app.ingestion.tasks import maintain_drive_sa

    service, session, _user, _orgs, _client = setup
    service.settings.google_drive_sa_enabled = False
    assert maintain_drive_sa(session=session, settings=service.settings) == {
        "checked": 0,
        "purged": 0,
        "errors": 0,
    }


def test_token_failure_marks_provider_error_without_reauth(setup):
    from app.ingestion.tasks import maintain_drive_sa
    from app.integrations.google_drive_sa import RobotUnavailable

    service, session, user, orgs, _client = setup
    source = enable(service, user, orgs[0])
    service.link(
        scope=OrganizationScope(orgs[0].id),
        user_id=user.id,
        source_id=source.id,
        folder_id="folder_123456",
    )

    def unavailable(source):
        raise RobotUnavailable("robot_unavailable")

    service.credentials = unavailable
    assert (
        maintain_drive_sa(session=session, settings=service.settings, service=service)["errors"]
        == 1
    )
    assert source.status == "provider_error"


def test_maintenance_restores_before_due_purge(setup):
    from app.ingestion.tasks import maintain_drive_sa

    service, session, user, orgs, client = setup
    source = enable(service, user, orgs[0])
    scope = OrganizationScope(orgs[0].id)
    linked = service.link(
        scope=scope, user_id=user.id, source_id=source.id, folder_id="folder_123456"
    )
    client.allowed = False
    service.recheck(source, now=datetime.now(UTC) - timedelta(days=15))
    service.recheck(source, now=datetime.now(UTC) - timedelta(days=14))
    client.allowed = True
    result = maintain_drive_sa(session=session, settings=service.settings, service=service)
    assert result["purged"] == 0
    assert linked.status == "verified"


def test_retained_chunks_are_hidden_from_evidence_api(setup):
    from fastapi import HTTPException

    from app.api.evidence import scoped_document

    service, session, user, orgs, client = setup
    source = enable(service, user, orgs[0])
    scope = OrganizationScope(orgs[0].id)
    link = service.link(
        scope=scope, user_id=user.id, source_id=source.id, folder_id="folder_123456"
    )
    workspace = session.get(WorkspaceFolder, link.workspace_folder_id)
    workspace.status = "ready"
    doc = Document(
        organization_id=scope.organization_id,
        workspace_folder_id=workspace.id,
        external_file_id="file_123456",
        name="doc",
        mime_type="text/plain",
        source_url="url",
        content_hash="h",
        index_status="indexed",
    )
    session.add(doc)
    session.flush()
    assert (
        scoped_document(
            session, organization_id=scope.organization_id, document_id=doc.id, user=user
        ).id
        == doc.id
    )
    client.allowed = False
    service.recheck(source)
    with pytest.raises(HTTPException) as error:
        scoped_document(
            session, organization_id=scope.organization_id, document_id=doc.id, user=user
        )
    assert error.value.status_code == 404


def test_purge_union_preserves_other_link_documents(setup):
    from app.library.models import LibraryNode
    from app.workspaces.service import WorkspaceScope, WorkspaceService

    service, session, user, orgs, _ = setup
    source = enable(service, user, orgs[0])
    scope = OrganizationScope(orgs[0].id)
    links = [
        service.link(
            scope=scope, user_id=user.id, source_id=source.id, folder_id=f"folder_12345{n}"
        )
        for n in range(2)
    ]
    union = WorkspaceService(session).select_scope(
        scope=scope,
        user_id=user.id,
        source_id=source.id,
        requested=WorkspaceScope(
            mode="selected", folder_ids=tuple(x.external_folder_id for x in links)
        ),
        uniform_access_confirmed=True,
        available_folder_names={x.external_folder_id: x.folder_name for x in links},
    )
    docs = []
    for n, link in enumerate(links):
        parent = LibraryNode(
            organization_id=scope.organization_id,
            source_id=source.id,
            external_id=link.external_folder_id,
            name="folder",
            kind="folder",
        )
        session.add(parent)
        session.flush()
        session.add(
            LibraryNode(
                organization_id=scope.organization_id,
                source_id=source.id,
                external_id=f"file_12345{n}",
                name="file",
                kind="file",
                parent_id=parent.id,
            )
        )
        doc = Document(
            organization_id=scope.organization_id,
            workspace_folder_id=union.id,
            external_file_id=f"file_12345{n}",
            name="doc",
            mime_type="text/plain",
            source_url="url",
            content_hash="h",
            index_status="indexed",
        )
        session.add(doc)
        docs.append(doc)
    session.flush()
    service.unlink(
        scope=scope, user_id=user.id, source_id=source.id, link_id=links[0].id, purge=True
    )
    assert session.get(Document, docs[0].id) is None
    assert session.get(Document, docs[1].id) is not None


def test_robot_scheduler_uses_folder_interval_and_flag(setup):
    from app.ingestion.tasks import schedule_connected_source_reconciliations

    service, session, user, orgs, _ = setup
    source = enable(service, user, orgs[0])
    scope = OrganizationScope(orgs[0].id)
    link = service.link(
        scope=scope, user_id=user.id, source_id=source.id, folder_id="folder_123456"
    )
    folder = session.get(WorkspaceFolder, link.workspace_folder_id)
    now = datetime.now(UTC)
    folder.last_synced_at = now - timedelta(minutes=20)
    source.last_synced_at = now
    folder.status = "ready"
    session.commit()
    calls = []
    service.settings.google_drive_sa_enabled = False
    assert (
        schedule_connected_source_reconciliations(
            session=session,
            settings=service.settings,
            now=now,
            send_task=lambda *a, **k: calls.append(k),
        )["enqueued"]
        == 0
    )
    service.settings.google_drive_sa_enabled = True
    assert (
        schedule_connected_source_reconciliations(
            session=session,
            settings=service.settings,
            now=now,
            send_task=lambda *a, **k: calls.append(k),
        )["enqueued"]
        == 1
    )
    assert len(calls) == 1


def test_unlink_does_not_extend_existing_revocation_retention(setup):
    service, _session, user, orgs, client = setup
    source = enable(service, user, orgs[0])
    scope = OrganizationScope(orgs[0].id)
    link = service.link(
        scope=scope, user_id=user.id, source_id=source.id, folder_id="folder_123456"
    )
    first_loss = datetime.now(UTC) - timedelta(days=10)
    client.allowed = False
    service.recheck(source, now=first_loss)
    from app.integrations.google_drive_sa_service import utc

    original_deadline = utc(link.purge_after)
    service.unlink(scope=scope, user_id=user.id, source_id=source.id, link_id=link.id)
    assert utc(link.purge_after) == original_deadline
