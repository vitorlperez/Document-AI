from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.integrations.models import DataSource
from app.organizations.models import Membership, MembershipRole, Organization
from app.spaces.backfill import backfill_default_spaces
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder
import pytest

pytestmark = pytest.mark.no_auto_spaces


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _legacy_org(engine):
    with sessionmaker(bind=engine).begin() as s:
        org = Organization(name="Acme")
        owner, member, gone = (User(email=f"{n}@example.test") for n in ("o", "m", "g"))
        s.add_all([org, owner, member, gone])
        s.flush()
        s.add_all([
            Membership(organization_id=org.id, user_id=owner.id, role=MembershipRole.OWNER, is_active=True),
            Membership(organization_id=org.id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True),
            Membership(organization_id=org.id, user_id=gone.id, role=MembershipRole.MEMBER, is_active=False),
        ])
        source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                            status="connected", connected_by_user_id=owner.id)
        s.add(source)
        s.flush()
        for name in ("a", "b"):
            s.add(WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id=name,
                                  name=name, uniform_access_confirmed=True, status="ready"))
        return org.id


def test_backfill_creates_geral_with_everyone_and_every_folder():
    engine = _engine()
    org_id = _legacy_org(engine)
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 1
    with sessionmaker(bind=engine)() as s:
        space = s.scalar(select(Space).where(Space.organization_id == org_id))
        assert (space.name, space.is_default) == ("Geral", True)
        members = s.execute(select(SpaceMember.role).where(SpaceMember.space_id == space.id)).scalars().all()
        assert sorted(members) == ["manager", "member"]  # owner -> manager; inactive membership skipped
        assert len(s.scalars(select(SpaceFolderGrant).where(SpaceFolderGrant.space_id == space.id)).all()) == 2


def test_backfill_is_idempotent():
    engine = _engine()
    _legacy_org(engine)
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 1
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 0
    with sessionmaker(bind=engine)() as s:
        assert len(s.scalars(select(Space)).all()) == 1
        assert len(s.scalars(select(SpaceMember)).all()) == 2


def test_reupgrade_after_downgrade_restores_geral_grants_and_missing_members():
    """A2: 0036 downgrade deletes the migration grants; the next upgrade must complete Geral, not skip the org."""
    from sqlalchemy import delete, update

    engine = _engine()
    org_id = _legacy_org(engine)
    with engine.begin() as connection:
        backfill_default_spaces(connection)
    with sessionmaker(bind=engine).begin() as s:
        geral_id = s.scalar(select(Space.id).where(Space.organization_id == org_id))
        s.execute(delete(SpaceFolderGrant))  # what the downgrade removes
        # a member who left Geral on purpose must stay out; a new active member must come in
        member_row = s.scalars(select(SpaceMember).where(SpaceMember.role == "member")).one()
        s.execute(update(SpaceMember).where(SpaceMember.id == member_row.id).values(removed_at=__import__("datetime").datetime.now()))
        newcomer = User(email="new@example.test")
        s.add(newcomer)
        s.flush()
        newcomer_id = newcomer.id
        s.add(Membership(organization_id=org_id, user_id=newcomer.id, role=MembershipRole.MEMBER, is_active=True))
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 1
    with sessionmaker(bind=engine)() as s:
        assert len(s.scalars(select(SpaceFolderGrant).where(SpaceFolderGrant.space_id == geral_id)).all()) == 2
        active = s.scalars(select(SpaceMember).where(SpaceMember.removed_at.is_(None))).all()
        assert len(active) == 2 and any(m.user_id == newcomer_id for m in active)
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 0


def test_backfill_leaves_deliberately_assigned_folders_alone_and_batches_inserts():
    engine = _engine()
    org_id = _legacy_org(engine)
    with engine.begin() as connection:
        backfill_default_spaces(connection)
    with sessionmaker(bind=engine).begin() as s:
        from sqlalchemy import delete
        rh = Space(organization_id=org_id, name="RH", name_key="rh")
        s.add(rh)
        s.flush()
        folder = s.scalars(select(WorkspaceFolder)).first()
        s.execute(delete(SpaceFolderGrant).where(SpaceFolderGrant.workspace_folder_id == folder.id))
        s.add(SpaceFolderGrant(organization_id=org_id, space_id=rh.id, workspace_folder_id=folder.id,
                               disclosure={"text_version": "v1"}))
        kept, rh_id = folder.id, rh.id
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 0  # every folder has an owner Space already
    with sessionmaker(bind=engine)() as s:
        assert [g.space_id for g in s.scalars(select(SpaceFolderGrant).where(SpaceFolderGrant.workspace_folder_id == kept))] == [rh_id]


def test_backfill_uses_one_statement_per_table_not_one_per_row():
    from sqlalchemy import event

    engine = _engine()
    with sessionmaker(bind=engine).begin() as s:
        org = Organization(name="Big")
        s.add(org)
        s.flush()
        users = [User(email=f"u{i}@x.test") for i in range(30)]
        s.add_all(users)
        s.flush()
        s.add_all([Membership(organization_id=org.id, user_id=u.id, role=MembershipRole.MEMBER, is_active=True) for u in users])
        source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                            status="connected", connected_by_user_id=users[0].id)
        s.add(source)
        s.flush()
        s.add_all([WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id=f"f{i}", name=f"f{i}",
                                   uniform_access_confirmed=True, status="ready") for i in range(30)])
    seen: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, st, p, ctx, many: seen.append((st, many)))
    with engine.begin() as connection:
        backfill_default_spaces(connection)
    inserts = [st for st, many in seen if st.lstrip().upper().startswith("INSERT")]
    assert len(inserts) <= 3  # spaces, members, grants (executemany batches)


def test_coverage_migration_covers_people_and_folders_in_no_space_and_is_idempotent():
    from app.spaces.backfill import ensure_default_space_coverage

    engine = _engine()
    org_id = _legacy_org(engine)
    with engine.begin() as connection:
        assert ensure_default_space_coverage(connection) == 1  # creates Geral with everyone and both folders
    with sessionmaker(bind=engine).begin() as s:
        rh = Space(organization_id=org_id, name="RH", name_key="rh")
        s.add(rh)
        s.flush()
        newcomer = User(email="late@example.test")
        s.add(newcomer)
        s.flush()
        s.add(Membership(organization_id=org_id, user_id=newcomer.id, role=MembershipRole.MEMBER, is_active=True))
        s.add(WorkspaceFolder(organization_id=org_id, source_id=s.scalars(select(WorkspaceFolder.source_id)).first(),
                              external_folder_id="c", name="c", uniform_access_confirmed=True, status="ready"))
    with engine.begin() as connection:
        assert ensure_default_space_coverage(connection) == 1
    with engine.begin() as connection:
        assert ensure_default_space_coverage(connection) == 0
    with sessionmaker(bind=engine)() as s:
        geral = s.scalar(select(Space).where(Space.is_default.is_(True)))
        assert len(s.scalars(select(SpaceFolderGrant).where(SpaceFolderGrant.space_id == geral.id)).all()) == 3
        assert len(s.scalars(select(SpaceMember).where(SpaceMember.space_id == geral.id)).all()) == 3


def test_coverage_migration_promotes_an_existing_geral_without_default_flag():
    from app.spaces.backfill import ensure_default_space_coverage

    engine = _engine()
    org_id = _legacy_org(engine)
    with sessionmaker(bind=engine).begin() as s:
        s.add(Space(organization_id=org_id, name="Geral", name_key="geral", is_default=False))
    with engine.begin() as connection:
        assert ensure_default_space_coverage(connection) == 1
    with sessionmaker(bind=engine)() as s:
        spaces = s.scalars(select(Space)).all()
        assert [(x.name, x.is_default) for x in spaces] == [("Geral", True)]
        assert len(s.scalars(select(SpaceMember)).all()) == 2
