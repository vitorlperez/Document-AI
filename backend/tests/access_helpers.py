"""Seed helpers: independent tenants without going through the login flow."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.access.keys import generate_api_key
from app.access.models import ALL_SCOPES, ApiKey, OrganizationAccessSettings
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import LibraryNode
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder


@dataclass(frozen=True)
class Tenant:
    organization_id: UUID
    user_id: UUID
    folder_id: UUID
    document_id: UUID


def seed_tenant(factory: sessionmaker[Session], name: str, text: str, *, api_enabled: bool = True) -> Tenant:
    with factory.begin() as session:
        org, user = Organization(name=name), User(email=f"{name.lower()}@example.test")
        session.add_all([org, user])
        session.flush()
        session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER, is_active=True))
        session.add(OrganizationAccessSettings(
            organization_id=org.id, public_api_enabled=api_enabled, mcp_enabled=api_enabled))
        source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                            status="connected", connected_by_user_id=user.id)
        session.add(source)
        session.flush()
        folder = WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id="f",
                                 name=f"{name} folder", uniform_access_confirmed=True, status="ready")
        session.add(folder)
        session.flush()
        document = Document(
            organization_id=org.id, workspace_folder_id=folder.id, external_file_id=f"{name}-doc",
            name=f"{name} plano.pdf", mime_type="application/pdf",
            source_url=f"https://drive.example.test/{name}", content_hash="a" * 64,
            processing_version="v1", index_status="indexed",
        )
        session.add(document)
        session.flush()
        session.add(DocumentChunk(
            organization_id=org.id, workspace_folder_id=folder.id, document_id=document.id, position=0,
            text=text, search_text=text.lower(), embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL,
        ))
        root = LibraryNode(organization_id=org.id, source_id=source.id, parent_id=None,
                           external_id="__company_library_source_root__", kind="source", name=name)
        session.add(root)
        session.flush()
        session.add(LibraryNode(organization_id=org.id, source_id=source.id, parent_id=root.id,
                                external_id=document.external_file_id, kind="file", name=document.name,
                                mime_type="application/pdf", source_url=document.source_url))
        return Tenant(org.id, user.id, folder.id, document.id)


def mint_key(factory: sessionmaker[Session], tenant: Tenant, *, scopes=ALL_SCOPES, node_ids=None,
             expires_in: timedelta | None = None, revoked: bool = False, rate: int = 60) -> str:
    generated = generate_api_key()
    with factory.begin() as session:
        session.add(ApiKey(
            organization_id=tenant.organization_id, created_by_user_id=tenant.user_id, name="test",
            prefix=generated.prefix, secret_hash=generated.secret_hash, scopes=sorted(scopes),
            node_ids=[str(item) for item in node_ids] if node_ids else None, rate_limit_per_minute=rate,
            expires_at=datetime.now(UTC) + expires_in if expires_in else None,
            revoked_at=datetime.now(UTC) if revoked else None,
        ))
    return generated.raw


def bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}
