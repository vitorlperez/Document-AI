"""T-H3: followed questions and saved queries respect Spaces and drop stale answers."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import SavedQuery
from app.audit_usage.service import SavedQueryService
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.models import Document
from app.notifications.followed import (
    clear_followed_state_for_lost_access,
    refresh_followed_queries,
)
from app.notifications.models import Notification
from tests.space_derived_helpers import CiteEverythingProvider, remove_from_space
from tests.spaces_helpers import seed_world


class CountingProvider(CiteEverythingProvider):
    def __init__(self):
        self.answers = 0

    def answer(self, *, question, evidence):
        self.answers += 1
        return super().answer(question=question, evidence=evidence)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db


def follow(session, world, who, folder="rh", last_answer=None):
    row = SavedQuery(organization_id=world.organization_id, workspace_folder_id=world.folders[folder],
                     user_id=world.users[who], name="politica", query="qual a politica salarial?", filters={},
                     followed=True, last_answer=last_answer, last_checked_at=datetime.now(UTC) - timedelta(days=2),
                     created_at=datetime.now(UTC) - timedelta(days=3))
    session.add(row)
    session.flush()
    return row


def touch(session, world, folder="rh"):
    for document in session.query(Document).filter_by(workspace_folder_id=world.folders[folder]):
        document.indexed_at = datetime.now(UTC)
    session.flush()


def test_refresh_skips_a_query_whose_owner_lost_the_folder_without_calling_the_model(session):
    world = seed_world(session)
    follow(session, world, "bruno")
    follow(session, world, "carla")
    touch(session, world)
    remove_from_space(session, world, "bruno", "rh")
    provider = CountingProvider()
    counts = refresh_followed_queries(session, workspace_folder_id=world.folders["rh"], provider=provider)
    assert counts["considered"] == 2 and counts["rerun"] == 1 and provider.answers == 1


def test_a_baseline_citing_something_no_longer_readable_is_treated_as_no_baseline_and_stays_silent(session):
    world = seed_world(session)
    ghost = "00000000-0000-0000-0000-00000000dead"
    row = follow(session, world, "carla", last_answer={"text": "antigo", "document_ids": [ghost], "at": "x"})
    touch(session, world)
    counts = refresh_followed_queries(session, workspace_folder_id=world.folders["rh"], provider=CountingProvider())
    assert counts["rerun"] == 1 and counts["notified"] == 0
    assert str(world.documents["rh"]) in row.last_answer["document_ids"]
    assert session.query(Notification).count() == 0


def test_notification_of_a_followed_change_records_provenance(session):
    world = seed_world(session)
    follow(session, world, "carla", last_answer={"text": "antigo", "document_ids": [str(world.documents["rh"])], "at": "x"})
    touch(session, world)
    refresh_followed_queries(session, workspace_folder_id=world.folders["rh"], provider=CountingProvider())
    note = session.query(Notification).one()
    assert note.data["provenance"] == {"document_ids": [str(world.documents["rh"])],
                                       "workspace_folder_ids": [str(world.folders["rh"])]}


def test_clear_followed_state_unfollows_and_wipes_the_stale_answer_after_losing_the_folder(session):
    world = seed_world(session)
    lost = follow(session, world, "bruno", last_answer={"text": "t", "document_ids": [str(world.documents["rh"])], "at": "x"})
    kept = follow(session, world, "bruno", folder="politicas", last_answer={"text": "t", "document_ids": [], "at": "x"})
    remove_from_space(session, world, "bruno", "rh")
    changed = clear_followed_state_for_lost_access(session, world.organization_id, world.users["bruno"])
    assert changed == 1
    assert lost.followed is False and lost.last_answer is None and lost.last_checked_at is None
    assert kept.followed is True and kept.last_answer is not None
    assert clear_followed_state_for_lost_access(session, world.organization_id, world.users["bruno"]) == 0


def test_reading_a_saved_query_of_a_folder_outside_the_spaces_is_denied(session):
    world = seed_world(session)
    row = follow(session, world, "bruno")
    remove_from_space(session, world, "bruno", "rh")
    scope = OrganizationScope(world.organization_id)
    with pytest.raises(GoogleAccessDenied):
        SavedQueryService(session).list(scope=scope, user_id=world.users["bruno"], workspace_folder_id=world.folders["rh"])
    with pytest.raises(GoogleAccessDenied):
        SavedQueryService(session).set_followed(scope=scope, user_id=world.users["bruno"], saved_query_id=row.id, followed=False)
