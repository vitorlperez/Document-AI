import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.questions import Evidence, GeneratedAnswer, QuestionService
from app.library.service import LibraryService
from app.organizations.models import Organization
from app.workspaces.service import WorkspaceService
from tests.spaces_helpers import FOLDERS, seed_world


class FakeProvider:
    def __init__(self):
        self.answer_calls: list[list[Evidence]] = []

    def embed(self, *, texts):
        return [[1.0, 0.0] for _ in texts]

    def answer(self, *, question, evidence):
        self.answer_calls.append(evidence)
        return GeneratedAnswer("ok", [1])

    def summarize_documents(self, *, question, evidence):
        return []

    def assess_summary(self, *, claims, evidence):
        return []


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def contexts(session, world, who, **kw):
    return LibraryService(session).question_contexts(
        scope=OrganizationScope(world.organization_id), user_id=world.users[who], **kw)


def test_question_contexts_return_only_accessible_folders_with_badges(session):
    world = seed_world(session)
    result = contexts(session, world, "daniel")
    assert {c.id for c in result} == {world.folders["politicas"], world.folders["diretoria"]}
    badges = {c.id: [s.name for s in c.spaces] for c in result}
    assert badges == {world.folders["politicas"]: ["Geral"], world.folders["diretoria"]: ["Diretoria"]}


def test_question_contexts_space_filter_narrows(session):
    world = seed_world(session)
    result = contexts(session, world, "carla", space_ids=[world.spaces["rh"]])
    assert [c.id for c in result] == [world.folders["rh"]]


def test_require_member_access_denies_folder_outside_spaces(session):
    world = seed_world(session)
    service = WorkspaceService(session)
    scope = OrganizationScope(world.organization_id)
    assert service.require_member_access(
        scope=scope, user_id=world.users["bruno"], workspace_folder_id=world.folders["rh"]).id == world.folders["rh"]
    with pytest.raises(GoogleAccessDenied, match="workspace access denied"):
        service.require_member_access(scope=scope, user_id=world.users["bruno"],
                                      workspace_folder_id=world.folders["diretoria"])
    assert {f.id for f in service.folders(scope=scope, user_id=world.users["bruno"])} == {
        world.folders["politicas"], world.folders["rh"]}


def _statements(session):
    seen: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute", lambda c, cur, st, p, ctx, m: seen.append(st))
    return seen


def test_ask_with_many_folders_runs_one_access_check(session):
    world = seed_world(session)
    seen = _statements(session)
    result = QuestionService(session, FakeProvider()).ask(
        scope=OrganizationScope(world.organization_id), user_id=world.users["carla"],
        workspace_folder_ids=list(world.folders.values()), question="politica?")
    assert result.confidence == "supported"
    memberships = [s for s in seen if "FROM memberships" in s or "JOIN memberships" in s]
    assert len(memberships) == 1, memberships  # one resolution for the whole question (spike M2)


def test_org_scope_question_for_daniel_never_cites_rh(session):
    world = seed_world(session)
    provider = FakeProvider()
    result = QuestionService(session, provider).ask_scope(
        scope=OrganizationScope(world.organization_id), user_id=world.users["daniel"],
        question="politica?", question_scope="organization")
    cited = {c.document_id for c in result.citations}
    assert cited and world.documents["rh"] not in cited
    assert cited <= {world.documents["politicas"], world.documents["diretoria"]}
    sent = {e.document_id for call in provider.answer_calls for e in call}
    assert world.documents["rh"] not in sent


def test_ask_for_a_folder_outside_the_spaces_is_denied(session):
    world = seed_world(session)
    with pytest.raises(GoogleAccessDenied):
        QuestionService(session, FakeProvider()).ask(
            scope=OrganizationScope(world.organization_id), user_id=world.users["bruno"],
            workspace_folder_ids=[world.folders["diretoria"]], question="reajuste?")


def test_request_filter_narrows_every_resolution_inside_it_and_never_widens(session):
    from app.spaces.filter import narrowed_to_spaces

    world = seed_world(session)
    with narrowed_to_spaces([world.spaces["rh"]]):
        assert [c.id for c in contexts(session, world, "carla")] == [world.folders["rh"]]
        assert contexts(session, world, "daniel") == []  # a Space daniel is not in adds nothing
        # C2: an explicit argument intersects with the request filter, it never replaces it
        assert contexts(session, world, "carla", space_ids=[world.spaces["geral"]]) == []
        assert [c.id for c in contexts(session, world, "carla", space_ids=[world.spaces["geral"], world.spaces["rh"]])] == [
            world.folders["rh"]]
    assert len(contexts(session, world, "carla")) == 3
