from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.organizations.models import Membership, Organization
from app.spaces.access import SpaceAccessResolver
from app.spaces.models import SpaceFolderGrant, SpaceMember
from app.spaces.service import SpaceNotFound
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def resolve(session, world, who, **kw):
    return SpaceAccessResolver(session).resolve(
        scope=OrganizationScope(world.organization_id), user_id=world.users[who], **kw)


def test_access_is_the_union_of_the_users_spaces(session):
    world = seed_world(session)
    assert resolve(session, world, "carla").folder_ids == {
        world.folders["politicas"], world.folders["rh"], world.folders["diretoria"]}
    assert resolve(session, world, "daniel").folder_ids == {world.folders["politicas"], world.folders["diretoria"]}


def test_org_owner_is_not_a_reader_of_spaces_they_are_not_in(session):
    world = seed_world(session)
    assert resolve(session, world, "eva").folder_ids == {world.folders["politicas"]}


def test_space_filter_only_narrows_and_never_widens(session):
    world = seed_world(session)
    rh, diretoria = world.spaces["rh"], world.spaces["diretoria"]
    assert resolve(session, world, "ana", space_ids=[rh]).folder_ids == {world.folders["rh"]}
    assert resolve(session, world, "ana", space_ids=[diretoria]).folder_ids == frozenset()  # ana is not in Diretoria
    assert resolve(session, world, "ana", space_ids=[]).folder_ids == frozenset()  # explicit empty = nothing


def test_strict_filter_rejects_foreign_spaces_as_not_found(session):
    world = seed_world(session)
    with pytest.raises(SpaceNotFound):
        resolve(session, world, "bruno", space_ids=[world.spaces["diretoria"]], strict=True)
    assert resolve(session, world, "bruno", space_ids=[world.spaces["rh"]], strict=True).folder_ids == {
        world.folders["rh"]}


def test_removed_member_revoked_grant_and_archived_space_all_cut_access(session):
    world = seed_world(session)
    now = datetime.now(UTC)
    session.query(SpaceMember).filter_by(space_id=world.spaces["rh"], user_id=world.users["bruno"]).update(
        {"removed_at": now})
    session.query(SpaceFolderGrant).filter_by(workspace_folder_id=world.folders["diretoria"]).update(
        {"revoked_at": now})
    session.flush()
    assert resolve(session, world, "bruno").folder_ids == {world.folders["politicas"]}
    assert resolve(session, world, "carla").folder_ids == {world.folders["politicas"], world.folders["rh"]}


def test_archived_space_grants_are_inert(session):
    from app.spaces.models import Space
    world = seed_world(session)
    session.get(Space, world.spaces["rh"]).archived_at = datetime.now(UTC)
    session.flush()
    assert resolve(session, world, "bruno").folder_ids == {world.folders["politicas"]}


def test_inactive_organization_membership_denies_before_looking_at_spaces(session):
    world = seed_world(session)
    session.query(Membership).filter_by(user_id=world.users["ana"]).update({"is_active": False})
    session.flush()
    with pytest.raises(SyncAccessDenied):
        resolve(session, world, "ana")


def test_badges_list_only_the_callers_own_spaces(session):
    world = seed_world(session)
    # the RH folder is also granted to Diretoria; Bruno is not in Diretoria
    session.add(SpaceFolderGrant(organization_id=world.organization_id, space_id=world.spaces["diretoria"],
                                 workspace_folder_id=world.folders["rh"], disclosure={"text_version": "v1"}))
    session.flush()
    assert [ref.name for ref in resolve(session, world, "bruno").spaces_of(world.folders["rh"])] == ["RH"]
    assert [ref.name for ref in resolve(session, world, "carla").spaces_of(world.folders["rh"])] == [
        "Diretoria", "RH"]


def test_database_errors_propagate_instead_of_opening_access(session, monkeypatch):
    world = seed_world(session)
    resolver = SpaceAccessResolver(session)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "execute", boom)
    with pytest.raises(RuntimeError):
        resolver.resolve(scope=OrganizationScope(world.organization_id), user_id=world.users["ana"])


def test_constant_number_of_statements_regardless_of_folder_count(session):
    world = seed_world(session)
    seen: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute", lambda c, cur, st, p, ctx, m: seen.append(st))
    resolve(session, world, "carla")
    assert len(seen) <= 4, seen


def test_off_mode_returns_every_folder_and_shadow_serves_legacy(session):
    world = seed_world(session)
    for mode in ("off", "shadow"):
        session.get(Organization, world.organization_id).spaces_resolver_mode = mode
        session.flush()
        assert resolve(session, world, "daniel").folder_ids == set(world.folders.values())
    session.get(Organization, world.organization_id).spaces_resolver_mode = "enforce"
    session.flush()
    assert resolve(session, world, "daniel").folder_ids == {world.folders["politicas"], world.folders["diretoria"]}


def test_shadow_logs_divergence_counts_only(session, caplog):
    world = seed_world(session)
    session.get(Organization, world.organization_id).spaces_resolver_mode = "shadow"
    session.flush()
    with caplog.at_level("WARNING", logger="app.spaces.access"):
        resolve(session, world, "daniel")  # legacy = 3 folders, spaces = 2 -> only_legacy == 1
    record = next(r for r in caplog.records if r.getMessage() == "spaces.shadow_divergence")
    assert (record.only_legacy, record.only_spaces) == (1, 0)
    assert "Diretoria" not in caplog.text  # only counts are logged, never names


def test_unknown_mode_fails_closed_to_spaces(session):
    world = seed_world(session, mode="bogus")
    assert resolve(session, world, "daniel").folder_ids == {world.folders["politicas"], world.folders["diretoria"]}


def test_require_folders_is_one_batch_and_denies_any_outsider(session):
    world = seed_world(session)
    resolver = SpaceAccessResolver(session)
    scope, user = OrganizationScope(world.organization_id), world.users["bruno"]
    rows = resolver.require_folders(scope=scope, user_id=user,
                                    workspace_folder_ids=[world.folders["rh"], world.folders["politicas"]])
    assert {row.id for row in rows} == {world.folders["rh"], world.folders["politicas"]}
    with pytest.raises(SyncAccessDenied):
        resolver.require_folders(scope=scope, user_id=user,
                                 workspace_folder_ids=[world.folders["rh"], world.folders["diretoria"]])
