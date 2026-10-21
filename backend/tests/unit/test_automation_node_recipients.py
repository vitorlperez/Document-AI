"""Automations over a library folder: a recipient reads the result only if they read EVERYTHING the creator's scope held.

The run uses the creator's rights over the whole mention; a recipient granted just a subfolder of it must not get
the answer (in-app, e-mail or webhook) built from the siblings they cannot read.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.audit_usage.models
import app.notifications.models  # noqa: F401
from app.automations.executor import execute_run
from app.automations.models import Automation, AutomationRun
from app.automations.scope import node_access, resolve_nodes
from app.automations.space_access import pause_automations_for_lost_access
from app.core.models import Base
from app.notifications.models import Notification
from tests.space_derived_helpers import CiteEverythingProvider
from tests.space_node_helpers import Tree

WEEKLY = {"frequency": "weekly", "weekday": 0, "hour": 8, "timezone": "America/Sao_Paulo"}


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def world(session):
    tree = Tree(session)
    tree.grant(session, "diretoria", tree.contratos)  # daniel/carla read all of Contratos
    tree.grant(session, "rh", tree.y2026)  # bruno reads only Contratos/2026
    return tree


def creators_documents(session, tree):
    selection = resolve_nodes(session, tree.scope, tree.world.users["daniel"], [tree.contratos])
    return selection.document_ids


def test_recipient_with_only_a_subfolder_is_not_ok_for_the_creators_whole_scope(session):
    tree = world(session)
    daniel, bruno, carla = (tree.world.users[who] for who in ("daniel", "bruno", "carla"))
    must_read = creators_documents(session, tree)
    assert must_read == {tree.doc["solto"], tree.doc["c2026"]}
    assert node_access(session, tree.scope, bruno, [tree.contratos]) == "ok"  # asks about his own reach: fine
    assert node_access(session, tree.scope, bruno, [tree.contratos], must_read=must_read) == "no_folder_access"
    assert node_access(session, tree.scope, carla, [tree.contratos], must_read=must_read) == "ok"
    assert node_access(session, tree.scope, daniel, [tree.contratos], must_read=must_read) == "ok"


def test_recipient_granted_the_same_subtree_is_ok(session):
    tree = world(session)
    selection = resolve_nodes(session, tree.scope, tree.world.users["bruno"], [tree.y2026])
    # creator whose scope is the subfolder itself: bruno reads all of it
    assert node_access(session, tree.scope, tree.world.users["bruno"], [tree.y2026],
                       must_read=selection.document_ids) == "ok"


def test_delivery_skips_the_recipient_who_cannot_read_every_document(session):
    tree = world(session)
    daniel, bruno, carla = (tree.world.users[who] for who in ("daniel", "bruno", "carla"))
    row = Automation(
        organization_id=tree.world.organization_id, created_by_user_id=daniel, name="Contratos", enabled=True,
        trigger_kind="schedule", trigger_config=WEEKLY, scope={"node_ids": [str(tree.contratos)]},
        prompt="Quais contratos existem?", template="table", output_formats=[], recipients=[str(daniel), str(bruno), str(carla)])
    session.add(row)
    session.flush()
    run = AutomationRun(automation_id=row.id, organization_id=row.organization_id, status="queued", trigger_ref="t-1")
    session.add(run)
    session.commit()
    assert execute_run(session, run.id, provider=CiteEverythingProvider()) == "ok"
    session.refresh(run)
    assert {item["user_id"]: item["reason"] for item in run.result["skipped_recipients"]} == {
        str(bruno): "no_folder_access"}
    assert run.result["notified"] == 2
    got = {note.user_id for note in session.query(Notification).filter_by(kind="automation_result")}
    assert got == {daniel, carla}


def test_a_recipient_who_lost_the_rest_of_the_scope_is_dropped_from_the_list(session):
    tree = world(session)
    daniel, bruno, carla = (tree.world.users[who] for who in ("daniel", "bruno", "carla"))
    row = Automation(
        organization_id=tree.world.organization_id, created_by_user_id=daniel, name="Contratos", enabled=True,
        trigger_kind="schedule", trigger_config=WEEKLY, scope={"node_ids": [str(tree.contratos)]},
        prompt="Quais contratos existem?", template="table", output_formats=[], recipients=[str(daniel), str(bruno), str(carla)])
    session.add(row)
    session.commit()
    pause_automations_for_lost_access(session, tree.world.organization_id, bruno)
    session.refresh(row)
    assert row.recipients == [str(daniel), str(carla)]
