"""T-D5: sync status and history respect the person's Spaces; admins see operational metadata of every scope."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.integrations.models import DataSource
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolder
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def world_with_jobs(session):
    world = seed_world(session)
    for key, folder_id in world.folders.items():
        session.add(ProcessingJob(organization_id=world.organization_id, workspace_folder_id=folder_id,
                                  status=ProcessingJobStatus.SYNCING, idempotency_key=f"job-{key}"))
    session.flush()
    return world


def syncs(session, world, who):
    return LibraryService(session).recent_syncs(scope=OrganizationScope(world.organization_id), user_id=world.users[who])


def test_member_sees_only_the_history_of_scopes_they_read(session):
    world = world_with_jobs(session)
    assert {s.workspace_name for s in syncs(session, world, "bruno")} == {"politicas", "rh"}
    assert {s.workspace_name for s in syncs(session, world, "daniel")} == {"politicas", "diretoria"}


def test_admin_sees_every_scope_status_even_outside_their_spaces(session):
    world = world_with_jobs(session)
    assert {s.workspace_name for s in syncs(session, world, "eva")} == {"politicas", "rh", "diretoria"}


def status_of(session, world, who):
    items = LibraryService(session).sync_status(scope=OrganizationScope(world.organization_id), user_id=world.users[who])
    return items


def test_sync_status_counts_only_readable_scopes_for_members(session):
    world = world_with_jobs(session)
    session.add(DataSource(organization_id=world.organization_id, provider="notion", encrypted_credentials="x",
                           status="connected", connected_by_user_id=world.users["eva"]))
    session.flush()
    # a source with no readable scope does not exist for a member; the admin sees it (operational view)
    assert [i["provider"] for i in status_of(session, world, "bruno")] == ["google_drive"]
    assert sorted(i["provider"] for i in status_of(session, world, "eva")) == ["google_drive", "notion"]


def test_sync_status_state_ignores_jobs_of_unreadable_scopes(session):
    world = world_with_jobs(session)
    session.query(ProcessingJob).filter_by(workspace_folder_id=world.folders["diretoria"]).update(
        {"status": ProcessingJobStatus.FAILED, "error_code": "boom"})
    session.query(WorkspaceFolder).filter_by(id=world.folders["diretoria"]).update({"status": "failed"})
    session.flush()
    assert status_of(session, world, "bruno")[0]["error_code"] is None  # Bruno cannot read Diretoria
    assert status_of(session, world, "carla")[0]["error_code"] == "boom"
