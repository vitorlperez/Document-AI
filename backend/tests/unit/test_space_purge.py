"""T-H6: real impact numbers and the 24 h purge job for derived content."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import SavedQuery
from app.automations.models import Automation, AutomationRun
from app.core.models import Base
from app.ingestion.tasks import beat_schedule, celery_app
from app.knowledge.derived import (
    derived_impact,
    purge_derived_for_folder,
    purge_derived_for_user,
    purge_hidden_derived,
)
from app.knowledge.derived_visibility import HIDDEN_NOTICE
from app.knowledge.models import Conversation, ConversationMessage
from app.notifications.models import Notification
from app.spaces.models import SpaceFolderGrant, SpaceMember
from tests.spaces_helpers import seed_world

WEEKLY = {"frequency": "weekly", "weekday": 0, "hour": 8, "timezone": "America/Sao_Paulo"}


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db


def derived_content(session, world, who="bruno"):
    """Bruno has content derived from RH and from Geral."""
    user = world.users[who]
    conversation = Conversation(organization_id=world.organization_id, user_id=user, title="c")
    session.add(conversation)
    session.flush()
    for position, key in enumerate(("rh", "politicas"), start=1):
        session.add(ConversationMessage(conversation_id=conversation.id, position=position * 2 - 1, role="user", content="pergunta"))
        session.add(ConversationMessage(
            conversation_id=conversation.id, position=position * 2, role="assistant", content=f"resposta {key}",
            context={}, response={"answer": f"resposta {key}", "citations": [{"document_id": str(world.documents[key])}]}))
    automations = {}
    for key in ("rh", "politicas"):
        row = Automation(organization_id=world.organization_id, created_by_user_id=user, name=f"auto {key}", enabled=True,
                         trigger_kind="schedule", trigger_config=WEEKLY, scope={"workspace_folder_ids": [str(world.folders[key])]},
                         prompt="x", template="table", output_formats=[], recipients=[])
        session.add(row)
        session.flush()
        session.add(AutomationRun(automation_id=row.id, organization_id=world.organization_id, status="ok", trigger_ref="r",
                                  result={"answer": f"resultado {key}", "citations": [{"document_id": str(world.documents[key])}]}))
        automations[key] = row
    queries = {}
    for key in ("rh", "politicas"):
        row = SavedQuery(organization_id=world.organization_id, workspace_folder_id=world.folders[key], user_id=user,
                         name=f"q {key}", query="qual?", filters={}, followed=True,
                         last_answer={"text": "t", "document_ids": [str(world.documents[key])], "at": "x"},
                         last_checked_at=datetime.now(UTC))
        session.add(row)
        queries[key] = row
    notes = {}
    for key in ("rh", "politicas"):
        note = Notification(organization_id=world.organization_id, user_id=user, kind="automation_result", title="t",
                            body=f"corpo {key}", data={"provenance": {"document_ids": [str(world.documents[key])],
                                                                       "workspace_folder_ids": [str(world.folders[key])]}})
        session.add(note)
        notes[key] = note
    session.flush()
    return conversation, automations, queries, notes


def leave_rh(session, world, hours_ago):
    member = session.query(SpaceMember).filter_by(space_id=world.spaces["rh"], user_id=world.users["bruno"], removed_at=None).one()
    member.removed_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    session.flush()


def test_impact_counts_only_what_disappears(session):
    world = seed_world(session)
    derived_content(session, world)
    impact = derived_impact(session, world.organization_id, world.users["bruno"], lost_folder_ids={world.folders["rh"]})
    assert impact == {"conversations_hidden": 1, "automations_paused": 1, "followed_queries_cleared": 1}
    none = derived_impact(session, world.organization_id, world.users["bruno"], lost_folder_ids=set())
    assert none == {"conversations_hidden": 0, "automations_paused": 0, "followed_queries_cleared": 0}


def test_impact_ignores_a_loss_that_another_space_still_covers(session):
    world = seed_world(session)
    derived_content(session, world)
    # carla is in RH and Diretoria: leaving Diretoria costs her nothing derived from RH
    impact = derived_impact(session, world.organization_id, world.users["carla"], lost_folder_ids={world.folders["diretoria"]})
    assert impact == {"conversations_hidden": 0, "automations_paused": 0, "followed_queries_cleared": 0}


def test_nothing_is_purged_before_24_hours(session):
    world = seed_world(session)
    _, automations, queries, notes = derived_content(session, world)
    leave_rh(session, world, hours_ago=1)
    counts = purge_hidden_derived(session)
    assert sum(counts.values()) == 0
    assert notes["rh"].body == "corpo rh" and queries["rh"].last_answer is not None and automations["rh"].enabled


def test_purge_after_24_hours_tombstones_and_is_idempotent(session):
    world = seed_world(session)
    conversation, automations, queries, notes = derived_content(session, world)
    leave_rh(session, world, hours_ago=25)
    counts = purge_hidden_derived(session)
    assert counts["notifications"] == 1 and counts["messages"] == 1 and counts["followed"] == 1
    assert counts["automations_paused"] == 1 and counts["runs"] == 1
    assert notes["rh"].body == HIDDEN_NOTICE and notes["rh"].data["hidden"] is True
    assert notes["politicas"].body == "corpo politicas"
    assert queries["rh"].last_answer is None and queries["rh"].followed is False and queries["politicas"].followed is True
    assert automations["rh"].enabled is False and automations["politicas"].enabled is True
    messages = {m.position: m for m in session.query(ConversationMessage).filter_by(conversation_id=conversation.id)}
    assert messages[2].content == HIDDEN_NOTICE and messages[2].response == {"hidden": True, "reason": "access_changed"}
    assert messages[1].content == "pergunta" and messages[4].content == "resposta politicas"  # the question and visible answers stay
    run = session.query(AutomationRun).join(Automation).filter(Automation.id == automations["rh"].id).one()
    assert run.result == {"hidden": True, "reason": "access_changed"}
    assert sum(purge_hidden_derived(session).values()) == 0  # idempotent


def test_folder_revocation_purges_for_every_member_that_depended_on_it(session):
    world = seed_world(session)
    _, _, queries, _notes = derived_content(session, world, "ana")  # ana manages RH
    _, _, bruno_queries, _ = derived_content(session, world, "bruno")
    grant = session.query(SpaceFolderGrant).filter_by(space_id=world.spaces["rh"], workspace_folder_id=world.folders["rh"]).one()
    grant.revoked_at = datetime.now(UTC) - timedelta(hours=30)
    session.flush()
    counts = purge_derived_for_folder(session, world.organization_id, world.folders["rh"])
    assert counts["followed"] == 2
    assert queries["rh"].last_answer is None and bruno_queries["rh"].last_answer is None
    assert queries["politicas"].last_answer is not None


def test_user_purge_is_a_noop_for_someone_who_lost_nothing(session):
    world = seed_world(session)
    derived_content(session, world, "carla")
    assert sum(purge_derived_for_user(session, world.organization_id, world.users["carla"]).values()) == 0


def test_the_job_is_scheduled_daily():
    entry = beat_schedule(15)["purge-hidden-derived"]
    assert entry["schedule"] == timedelta(days=1)
    assert entry["task"] in celery_app.tasks
