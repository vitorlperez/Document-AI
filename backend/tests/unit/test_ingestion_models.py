from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User  # noqa: F401 - registers referenced table metadata
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.integrations.models import DataSource  # noqa: F401 - registers referenced table metadata
from app.knowledge.models import Document, DocumentChunk
from app.organizations.models import (
    Organization,  # noqa: F401 - registers referenced table metadata
)
from app.workspaces.models import (
    WorkspaceFolder,  # noqa: F401 - registers referenced table metadata
)


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


def test_processing_job_has_explicit_lifecycle_and_organization_folder_scope() -> None:
    columns = ProcessingJob.__table__.c

    assert {"queued", "syncing", "ready", "partial_failure", "failed"} == {
        status.value for status in ProcessingJobStatus
    }
    assert {"organization_id", "workspace_folder_id", "idempotency_key", "status"} <= set(columns.keys())
    assert columns.idempotency_key.unique is True
    assert columns.organization_id.nullable is False
    assert columns.workspace_folder_id.nullable is False


def test_document_and_chunk_models_keep_required_tenant_and_folder_scope() -> None:
    document_columns = Document.__table__.c
    chunk_columns = DocumentChunk.__table__.c

    assert {"organization_id", "workspace_folder_id", "external_file_id", "content_hash", "index_status"} <= set(
        document_columns.keys()
    )
    assert {"organization_id", "workspace_folder_id", "document_id", "position", "text"} <= set(
        chunk_columns.keys()
    )
    assert all(
        columns.organization_id.nullable is False and columns.workspace_folder_id.nullable is False
        for columns in (document_columns, chunk_columns)
    )


def test_document_external_id_is_unique_within_workspace_folder(session: Session) -> None:
    organization_id = uuid4()
    workspace_folder_id = uuid4()
    document = Document(
        organization_id=organization_id,
        workspace_folder_id=workspace_folder_id,
        external_file_id="drive-file-1",
        name="Briefing.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/file/drive-file-1",
        content_hash="a" * 64,
        index_status="ready",
    )
    session.add(document)
    session.commit()

    session.add(
        Document(
            organization_id=organization_id,
            workspace_folder_id=workspace_folder_id,
            external_file_id="drive-file-1",
            name="Duplicate.pdf",
            mime_type="application/pdf",
            source_url="https://drive.example.test/file/drive-file-1",
            content_hash="b" * 64,
            index_status="ready",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_external_file_can_exist_in_another_workspace_folder(session: Session) -> None:
    organization_id = uuid4()
    first_folder_id, second_folder_id = uuid4(), uuid4()
    for folder_id in (first_folder_id, second_folder_id):
        session.add(
            Document(
                organization_id=organization_id,
                workspace_folder_id=folder_id,
                external_file_id="drive-file-1",
                name="Briefing.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/file/drive-file-1",
                content_hash="a" * 64,
                index_status="ready",
            )
        )

    session.commit()
    assert session.query(Document).count() == 2
