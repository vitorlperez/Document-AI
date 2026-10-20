"""Shared pieces for the Space-derivatives tests (citation seals, hiding, purge)."""

from sqlalchemy.orm import Session

from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL, GeneratedAnswer
from app.spaces.models import SpaceFolderGrant, SpaceMember
from tests.spaces_helpers import World


class CiteEverythingProvider:
    """Embeds every text identically and cites every evidence item it receives."""

    def embed(self, *, texts):
        return [[1.0, 0.0] for _ in texts]

    def answer(self, *, question, evidence):
        return GeneratedAnswer("Resposta fundamentada.", list(range(1, len(evidence) + 1)))


def add_shared_copy(session: Session, world: World, folder_keys=("politicas", "rh"), *, external_id="shared-doc",
                    name="ferias-compartilhado.pdf", text="calendario compartilhado de ferias"):
    """The same source file indexed in two folders (two Document rows, one logical file)."""
    ids = {}
    for key in folder_keys:
        folder_id = world.folders[key]
        document = Document(
            organization_id=world.organization_id, workspace_folder_id=folder_id, external_file_id=external_id,
            name=name, mime_type="application/pdf", source_url="https://drive.example.test/shared",
            content_hash="b" * 64, processing_version="v1", index_status="indexed")
        session.add(document)
        session.flush()
        session.add(DocumentChunk(
            organization_id=world.organization_id, workspace_folder_id=folder_id, document_id=document.id,
            position=0, text=text, search_text=text.lower(), embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
        ids[key] = document.id
    session.flush()
    return ids


def remove_from_space(session: Session, world: World, who: str, space: str) -> None:
    from datetime import UTC, datetime

    member = session.query(SpaceMember).filter_by(
        space_id=world.spaces[space], user_id=world.users[who], removed_at=None).one()
    member.removed_at = datetime.now(UTC)
    session.flush()


def revoke_folder_grant(session: Session, world: World, space: str, folder: str) -> None:
    from datetime import UTC, datetime

    grant = session.query(SpaceFolderGrant).filter_by(
        space_id=world.spaces[space], workspace_folder_id=world.folders[folder], revoked_at=None).one()
    grant.revoked_at = datetime.now(UTC)
    session.flush()
