import io
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.organizations.models import Membership, MembershipRole, Organization
from app.spaces.models import SpaceFolderGrant, SpaceMember
from app.spaces.rollout import run
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def _cli(session, *argv):
    out = io.StringIO()
    code = run(list(argv), session, out)
    return code, out.getvalue()


def _mode(session, org_id):
    session.expire_all()
    return session.get(Organization, org_id).spaces_resolver_mode


def test_shadow_and_off_are_always_allowed_even_with_pending_items(session):
    world = seed_world(session, mode="off")
    session.execute(delete(SpaceFolderGrant))
    session.commit()
    assert _cli(session, "shadow", "--organization", str(world.organization_id))[0] == 0
    assert _mode(session, world.organization_id) == "shadow"
    assert _cli(session, "off", "--organization", str(world.organization_id))[0] == 0
    assert _mode(session, world.organization_id) == "off"


def test_enforce_refuses_a_folder_without_space_unless_forced(session):
    world = seed_world(session, mode="shadow")
    session.execute(delete(SpaceFolderGrant).where(SpaceFolderGrant.workspace_folder_id == world.folders["rh"]))
    session.commit()
    code, text = _cli(session, "enforce", "--organization", str(world.organization_id))
    assert code == 2 and "sem Espaço" in text
    assert _mode(session, world.organization_id) == "shadow"
    assert _cli(session, "enforce", "--organization", str(world.organization_id), "--force")[0] == 0
    assert _mode(session, world.organization_id) == "enforce"


def test_enforce_refuses_an_active_person_in_no_space(session):
    world = seed_world(session, mode="shadow")
    stranger = User(email="novo@acme.test")
    session.add(stranger)
    session.flush()
    session.add(Membership(organization_id=world.organization_id, user_id=stranger.id,
                           role=MembershipRole.MEMBER, is_active=True))
    session.commit()
    assert _cli(session, "enforce", "--organization", str(world.organization_id))[0] == 2
    assert _mode(session, world.organization_id) == "shadow"


def test_enforce_passes_for_a_complete_organization(session):
    world = seed_world(session, mode="shadow")
    assert _cli(session, "enforce", "--organization", str(world.organization_id))[0] == 0
    assert _mode(session, world.organization_id) == "enforce"


def test_all_clean_skips_an_organization_whose_spaces_diverge_from_legacy(session):
    world = seed_world(session, mode="shadow")  # Bruno does not read Diretoria in Spaces but does in legacy
    code, text = _cli(session, "enforce", "--all-clean")
    assert code == 0 and "promovidas=0" in text
    assert _mode(session, world.organization_id) == "shadow"


def test_unknown_organization_is_a_usage_error(session):
    assert _cli(session, "enforce", "--organization", str(uuid4()))[0] == 1


def test_report_prints_counts_only(session):
    seed_world(session, mode="shadow", name="Segredo SA")
    code, text = _cli(session, "report")
    assert code == 0
    assert "folders_without_space=0" in text and "people_without_space=0" in text
    assert "Segredo" not in text and "rh.pdf" not in text


def test_all_clean_promotes_only_clean_shadow_organizations(session):
    clean = seed_world(session, mode="shadow", name="Limpa")
    for space_id in clean.spaces.values():  # everyone reads everything: Spaces and legacy agree
        for user_id in clean.users.values():
            if session.scalar(select(SpaceMember.id).where(SpaceMember.space_id == space_id,
                                                           SpaceMember.user_id == user_id)) is None:
                session.add(SpaceMember(organization_id=clean.organization_id, space_id=space_id, user_id=user_id,
                                        role="member"))
    dirty = seed_world(session, mode="shadow", name="Suja")
    off = seed_world(session, mode="off", name="Desligada")
    session.execute(delete(SpaceFolderGrant).where(SpaceFolderGrant.organization_id == dirty.organization_id))
    session.commit()
    code, text = _cli(session, "enforce", "--all-clean")
    assert code == 0 and "promovidas=1" in text
    assert _mode(session, clean.organization_id) == "enforce"
    assert _mode(session, dirty.organization_id) == "shadow"
    assert _mode(session, off.organization_id) == "off"
