"""Inconsistent legacy foreign keys cannot cross service tenant boundaries."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import IngestionService, SyncAccessDenied
from app.integrations.models import DataSource
from app.library.service import LibraryService
from app.organizations.models import Organization
from app.workspaces.models import WorkspaceFolder


def test_cross_tenant_source_blocks_folder_and_library_projection() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = Organization(id=uuid4(), name="First")
        second = Organization(id=uuid4(), name="Second")
        user = User(id=uuid4(), email="owner@example.test")
        session.add_all([first, second, user])
        session.flush()
        source = DataSource(
            id=uuid4(), organization_id=second.id, provider="google_drive",
            connected_by_user_id=user.id,
        )
        folder = WorkspaceFolder(
            id=uuid4(), organization_id=first.id, source_id=source.id,
            external_folder_id="root", name="Root", uniform_access_confirmed=True,
        )
        session.add_all([source, folder])
        session.flush()

        with pytest.raises(SyncAccessDenied):
            IngestionService(session).require_folder(
                scope=OrganizationScope(first.id), workspace_folder_id=folder.id,
            )
        with pytest.raises(SyncAccessDenied):
            LibraryService(session).project_successful_sync(
                organization_id=first.id, source=source, documents=[], folders=[],
            )
    engine.dispose()
