"""T-E3: one file indexed in two folders is one hit, carrying every one of the caller's Spaces that grant it."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.knowledge.retrieval import RetrievalService
from app.library.service import LibraryService
from tests.space_derived_helpers import add_shared_copy
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def search(session, world, who, query="calendario compartilhado de ferias"):
    scope = OrganizationScope(world.organization_id)
    selection = LibraryService(session).resolve_question_selection(
        scope=scope, user_id=world.users[who], providers=["google_drive"], mentions=[])
    return RetrievalService(session).search(scope=scope, user_id=world.users[who], query=query, selection=selection)


@pytest.mark.parametrize("who,expected", [("carla", ["Geral", "RH"]), ("bruno", ["Geral", "RH"]), ("daniel", ["Geral"])])
def test_a_file_in_two_folders_is_one_hit_with_accumulated_seals(session, who, expected):
    world = seed_world(session)
    add_shared_copy(session, world, folder_keys=("politicas", "rh"))
    hits = [hit for hit in search(session, world, who) if hit.title == "ferias-compartilhado.pdf"]
    assert len(hits) == 1
    assert sorted(ref.name for ref in hits[0].spaces) == expected


def test_no_hit_repeats_title_and_snippet(session):
    world = seed_world(session)
    add_shared_copy(session, world, folder_keys=("politicas", "rh", "diretoria"))
    hits = search(session, world, "carla")
    keys = [(hit.title, hit.snippet) for hit in hits]
    assert len(keys) == len(set(keys))


def test_hits_of_unrelated_files_keep_their_own_single_seal(session):
    world = seed_world(session)
    hits = {hit.title: hit for hit in search(session, world, "carla", query="reajuste diretoria")}
    assert [ref.name for ref in hits["diretoria.pdf"].spaces] == ["Diretoria"]
