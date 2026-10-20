"""T-H2: automation runs record provenance; losing a folder pauses the creator's automations; results hide."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.automations.executor import execute_run
from app.automations.models import Automation, AutomationRun
from app.automations.space_access import pause_automations_for_lost_access
from app.core.models import Base
from app.notifications.models import Notification
from tests.space_derived_helpers import CiteEverythingProvider
from tests.spaces_helpers import seed_world

WEEKLY = {"frequency": "weekly", "weekday": 0, "hour": 8, "timezone": "America/Sao_Paulo"}


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db


def automation(session, world, creator, folders, recipients=(), name="Relatorio"):
    row = Automation(
        organization_id=world.organization_id, created_by_user_id=world.users[creator], name=name, enabled=True,
        trigger_kind="schedule", trigger_config=WEEKLY, scope={"workspace_folder_ids": [str(world.folders[k]) for k in folders]},
        prompt="Resuma.", template="table", output_formats=[], recipients=[str(world.users[r]) for r in recipients])
    session.add(row)
    session.flush()
    return row


def queue(session, row):
    run = AutomationRun(automation_id=row.id, organization_id=row.organization_id, status="queued", trigger_ref=f"t-{row.id}-{len(session.new)}")
    session.add(run)
    session.commit()
    return run


def test_execution_records_provenance_of_what_it_cited(session):
    world = seed_world(session)
    row = automation(session, world, "carla", ["diretoria"])
    run = queue(session, row)
    assert execute_run(session, run.id, provider=CiteEverythingProvider()) == "ok"
    session.refresh(run)
    assert run.result["provenance"] == {
        "document_ids": [str(world.documents["diretoria"])], "workspace_folder_ids": [str(world.folders["diretoria"])]}
    note = session.query(Notification).filter_by(kind="automation_result", user_id=world.users["carla"]).one()
    assert note.data["provenance"] == run.result["provenance"]


def test_creator_who_lost_the_folder_gets_creator_access_lost_then_the_automation_is_paused(session):
    world = seed_world(session)
    row = automation(session, world, "carla", ["diretoria"])
    session.commit()
    from datetime import UTC, datetime

    from app.spaces.models import SpaceMember
    session.query(SpaceMember).filter_by(space_id=world.spaces["diretoria"], user_id=world.users["carla"]).update(
        {"removed_at": datetime.now(UTC)})
    session.commit()
    run = queue(session, row)
    assert execute_run(session, run.id, provider=CiteEverythingProvider()) == "error"
    session.refresh(run)
    assert run.error_code == "creator_access_lost"
    paused = pause_automations_for_lost_access(
        session, world.organization_id, world.users["carla"], {world.folders["diretoria"]})
    assert paused == [row.id]
    session.refresh(row)
    assert row.enabled is False
    notes = session.query(Notification).filter_by(kind="automation_paused", user_id=world.users["carla"]).all()
    assert len(notes) == 1 and str(row.id) == notes[0].data["automation_id"]
    # idempotent: nothing left to pause, no second notification
    assert pause_automations_for_lost_access(session, world.organization_id, world.users["carla"], set()) == []
    assert session.query(Notification).filter_by(kind="automation_paused").count() == 1


def test_automations_still_inside_the_creators_access_are_not_paused(session):
    world = seed_world(session)
    row = automation(session, world, "carla", ["politicas"])
    session.commit()
    assert pause_automations_for_lost_access(session, world.organization_id, world.users["carla"], {world.folders["rh"]}) == []
    session.refresh(row)
    assert row.enabled is True


def test_recipient_without_access_to_a_scope_folder_is_skipped_and_cleaned_from_the_list(session):
    world = seed_world(session)
    row = automation(session, world, "carla", ["diretoria"], recipients=["bruno"])
    run = queue(session, row)
    execute_run(session, run.id, provider=CiteEverythingProvider())
    session.refresh(run)
    assert run.result["skipped_recipients"] == [{"user_id": str(world.users["bruno"]), "reason": "no_folder_access"}]
    pause_automations_for_lost_access(session, world.organization_id, world.users["bruno"], {world.folders["diretoria"]})
    session.refresh(row)
    assert row.recipients == [] and row.enabled is True
