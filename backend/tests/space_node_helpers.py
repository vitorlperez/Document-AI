"""A Drive tree inside ONE synchronization, for folder-level Space grants (see test_space_node_grants).

``shared`` (granted to nobody) holds ``Contratos/(solto.pdf, 2026/c2026.pdf)`` and ``Financeiro/balanco.pdf``."""

from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.spaces.access import SpaceAccessResolver
from app.spaces.models import SpaceNodeGrant
from app.workspaces.models import WorkspaceFolder
from tests.spaces_helpers import World, seed_world

TEXTS = {
    "solto": "contrato solto na pasta contratos",
    "c2026": "contrato de 2026 assinado",
    "balanco": "balanco financeiro confidencial",
}


class Tree:
    def __init__(self, session: Session, world: World | None = None):
        self.world = world = world or seed_world(session)
        org, source = world.organization_id, world.source_id
        self.scope = OrganizationScope(org)
        shared = WorkspaceFolder(organization_id=org, source_id=source, external_folder_id="shared", name="shared",
                                 uniform_access_confirmed=True, status="ready")
        session.add(shared)
        session.flush()
        self.shared = shared.id

        def folder(key, parent):
            node = LibraryNode(organization_id=org, source_id=source, parent_id=parent, external_id=f"fld-{key}",
                               kind="folder", name=key)
            session.add(node)
            session.flush()
            return node.id

        def file(key, parent):
            document = Document(
                organization_id=org, workspace_folder_id=shared.id, external_file_id=f"file-{key}", name=f"{key}.pdf",
                mime_type="application/pdf", source_url=f"https://drive.example.test/{key}", content_hash="b" * 64,
                processing_version="v1", index_status="indexed")
            session.add(document)
            session.flush()
            session.add(DocumentChunk(
                organization_id=org, workspace_folder_id=shared.id, document_id=document.id, position=0,
                text=TEXTS[key], search_text=TEXTS[key].lower(), embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
            node = LibraryNode(organization_id=org, source_id=source, parent_id=parent, external_id=f"file-{key}",
                               kind="file", name=f"{key}.pdf", mime_type="application/pdf")
            session.add(node)
            session.flush()
            return document.id, node.id

        root = world.nodes["source"]
        self.contratos, self.financeiro = folder("Contratos", root), folder("Financeiro", root)
        self.y2026 = folder("2026", self.contratos)
        self.doc, self.node = {}, {}
        for key, parent in (("solto", self.contratos), ("c2026", self.y2026), ("balanco", self.financeiro)):
            self.doc[key], self.node[key] = file(key, parent)
        session.flush()

    def grant(self, session, space, folder_id, **kw):
        node = session.get(LibraryNode, folder_id)
        session.add(SpaceNodeGrant(
            organization_id=self.world.organization_id, space_id=self.world.spaces[space], source_id=node.source_id,
            external_id=node.external_id, name=node.name, disclosure={"text_version": "v1"}, **kw))
        session.flush()

    def access(self, session, who):
        return SpaceAccessResolver(session).resolve(scope=self.scope, user_id=self.world.users[who])

    def visible(self, session, who, parent):
        page = LibraryService(session).children(
            scope=self.scope, user_id=self.world.users[who], parent_id=parent, page=1, page_size=50)
        return {node.name for node in page.items}
