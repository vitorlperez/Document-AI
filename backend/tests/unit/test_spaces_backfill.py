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
        assert s.get(Organization, org_id).spaces_resolver_mode == "shadow"


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


def test_new_organizations_default_to_off_mode():
    engine = _engine()
    org_id = _legacy_org(engine)
    with sessionmaker(bind=engine)() as s:
        assert s.get(Organization, org_id).spaces_resolver_mode == "off"
