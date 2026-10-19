"""Acme multi-Space world for tests (ADR-0021): five people, three Spaces, three scopes, one document each."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import LibraryNode
from app.organizations.models import Membership, MembershipRole, Organization
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder

# folder key -> (Space that owns it, document text)
FOLDERS = {
    "politicas": ("geral", "politica de ferias para todos"),
    "rh": ("rh", "politica salarial confidencial do rh"),
    "diretoria": ("diretoria", "reajuste 2027 da diretoria"),
}
# person -> (organization role, {space: space role})
PEOPLE = {
    "eva": (MembershipRole.OWNER, {"geral": "manager"}),
    "ana": (MembershipRole.MEMBER, {"geral": "member", "rh": "manager"}),
    "bruno": (MembershipRole.MEMBER, {"geral": "member", "rh": "member"}),
    "carla": (MembershipRole.MEMBER, {"geral": "member", "rh": "member", "diretoria": "member"}),
    "daniel": (MembershipRole.MEMBER, {"geral": "member", "diretoria": "member"}),
}
SPACE_NAMES = {"geral": "Geral", "rh": "RH", "diretoria": "Diretoria"}


@dataclass(frozen=True)
class World:
    organization_id: UUID
    source_id: UUID
    users: dict[str, UUID]
    spaces: dict[str, UUID]
    folders: dict[str, UUID]
    documents: dict[str, UUID]
    nodes: dict[str, UUID]  # "source" root plus one file node per folder key


def seed_world(session: Session, *, mode: str = "enforce", name: str = "Acme") -> World:
    org = Organization(name=name, spaces_resolver_mode=mode)
    session.add(org)
    session.flush()
    users: dict[str, UUID] = {}
    for who, (role, _) in PEOPLE.items():
        user = User(email=f"{who}@{name.lower()}.test")
        session.add(user)
        session.flush()
        session.add(Membership(organization_id=org.id, user_id=user.id, role=role, is_active=True))
        users[who] = user.id
    spaces: dict[str, UUID] = {}
    for key, space_name in SPACE_NAMES.items():
        space = Space(organization_id=org.id, name=space_name, name_key=space_name.casefold(),
                      is_default=key == "geral")
        session.add(space)
        session.flush()
        spaces[key] = space.id
    for who, (_, memberships) in PEOPLE.items():
        for space_key, space_role in memberships.items():
            session.add(SpaceMember(organization_id=org.id, space_id=spaces[space_key], user_id=users[who],
                                    role=space_role))
    source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                        status="connected", connected_by_user_id=users["eva"])
    session.add(source)
    session.flush()
    root = LibraryNode(organization_id=org.id, source_id=source.id, parent_id=None,
                       external_id="__company_library_source_root__", kind="source", name="Google Drive")
    session.add(root)
    session.flush()
    folders: dict[str, UUID] = {}
    documents: dict[str, UUID] = {}
    nodes = {"source": root.id}
    for key, (space_key, text) in FOLDERS.items():
        folder = WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id=key, name=key,
                                 uniform_access_confirmed=True, status="ready")
        session.add(folder)
        session.flush()
        session.add(SpaceFolderGrant(organization_id=org.id, space_id=spaces[space_key],
                                     workspace_folder_id=folder.id, disclosure={"text_version": "v1"}))
        document = Document(
            organization_id=org.id, workspace_folder_id=folder.id, external_file_id=f"{key}-doc",
            name=f"{key}.pdf", mime_type="application/pdf", source_url=f"https://drive.example.test/{key}",
            content_hash="a" * 64, processing_version="v1", index_status="indexed")
        session.add(document)
        session.flush()
        session.add(DocumentChunk(
            organization_id=org.id, workspace_folder_id=folder.id, document_id=document.id, position=0,
            text=text, search_text=text.lower(), embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
        node = LibraryNode(organization_id=org.id, source_id=source.id, parent_id=root.id,
                           external_id=document.external_file_id, kind="file", name=document.name,
                           mime_type="application/pdf", source_url=document.source_url)
        session.add(node)
        session.flush()
        folders[key], documents[key], nodes[key] = folder.id, document.id, node.id
    return World(org.id, source.id, users, spaces, folders, documents, nodes)
