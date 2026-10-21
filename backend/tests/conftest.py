import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "postgres: requires a disposable PostgreSQL TEST_DATABASE_URL")
    config.addinivalue_line("markers", "no_auto_spaces: the test builds its own Spaces; no fixture auto-enrolment")


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the explicitly configured disposable PostgreSQL database URL.

    Integration tests never infer this from application configuration so a local
    developer database cannot accidentally be modified by the test suite.
    """
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL integration tests require TEST_DATABASE_URL")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL")
    return database_url


@pytest.fixture(autouse=True)
def no_manual_sync_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests trigger several manual syncs back to back; the cooldown has its own test."""
    from app.library import manual_sync

    monkeypatch.setattr(manual_sync, "SYNC_COOLDOWN_SECONDS", 0)


@pytest.fixture(autouse=True)
def stub_google_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing disconnect tests must never revoke credentials over the network."""
    import httpx

    original = httpx.post

    def post(url, **kwargs):
        if url == "https://oauth2.googleapis.com/revoke":
            return httpx.Response(200, request=httpx.Request("POST", url))
        return original(url, **kwargs)

    monkeypatch.setattr(httpx, "post", post)


AUTO_GERAL = "__test_default__"
AUTO_SPACES = {"on": True}


@pytest.fixture(autouse=True)
def auto_default_space(request: pytest.FixtureRequest):
    """``@pytest.mark.no_auto_spaces`` (or a module ``pytestmark``) turns the fixture hook below off."""
    AUTO_SPACES["on"] = request.node.get_closest_marker("no_auto_spaces") is None
    yield
    AUTO_SPACES["on"] = True


def _install_auto_default_space() -> None:
    """Spaces always enforce, so a fixture organization with no Space would see nothing.

    Production guarantees "Geral" at organization creation, on invitation accept and on folder selection (and migration
    0038 for old data). Fixtures insert rows directly, so this session hook plays that role: people and folders
    created through a session join the organization's default Space (an auto "Geral" is created when the organization
    has none). Idempotent with the services, which enrol explicitly. Opt out per session with
    ``session.info["no_auto_spaces"] = True`` (``seed_world`` and the Space-management tests do).
    """
    from uuid import uuid4

    def _auto(row):
        row._auto_fixture = True
        return row

    from sqlalchemy import event, select
    from sqlalchemy.orm import Session

    from app.organizations.models import Membership, MembershipRole
    from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
    from app.workspaces.models import WorkspaceFolder

    @event.listens_for(Session, "after_flush")
    def enroll_fixture_rows(session: Session, flush_context) -> None:
        if session.info.get("no_auto_spaces") or not AUTO_SPACES["on"]:
            return
        people = [o for o in session.new if isinstance(o, Membership) and o.is_active is not False]
        folders = [o for o in session.new if isinstance(o, WorkspaceFolder)]
        orgs = {o.organization_id for o in (*people, *folders) if o.organization_id is not None}
        if not orgs:
            return
        with session.no_autoflush:
            for org_id in orgs:
                default = session.scalar(select(Space.id).where(
                    Space.organization_id == org_id, Space.is_default.is_(True), Space.archived_at.is_(None)))
                if default is None:
                    if session.scalar(select(Space.id).where(Space.organization_id == org_id).limit(1)):
                        continue  # the organization manages its own Spaces and has no default one
                    default = uuid4()
                    session.add(Space(id=default, organization_id=org_id, name="Geral", name_key="geral",
                                      is_default=True, description=AUTO_GERAL))
                for member in (p for p in people if p.organization_id == org_id):
                    if session.scalar(select(SpaceMember.id).where(
                            SpaceMember.space_id == default, SpaceMember.user_id == member.user_id)):
                        continue
                    session.add(_auto(SpaceMember(
                        organization_id=org_id, space_id=default, user_id=member.user_id,
                        role="manager" if member.role in (MembershipRole.OWNER, MembershipRole.ADMIN) else "member")))
                for folder in (f for f in folders if f.organization_id == org_id):
                    session.add(_auto(SpaceFolderGrant(
                        organization_id=org_id, space_id=default, workspace_folder_id=folder.id,
                        disclosure={"text_version": "test"})))

    @event.listens_for(Session, "before_flush")
    def drop_duplicated_auto_rows(session: Session, flush_context, instances) -> None:
        """A service that enrols explicitly wins over the fixture hook's identical row."""
        def key(o):
            return (o.space_id, o.user_id) if isinstance(o, SpaceMember) else (o.space_id, o.workspace_folder_id)

        rows = [o for o in session.new if isinstance(o, (SpaceMember, SpaceFolderGrant))]
        explicit = {(type(o), key(o)) for o in rows if not getattr(o, "_auto_fixture", False)}
        for row in rows:
            if getattr(row, "_auto_fixture", False) and (type(row), key(row)) in explicit:
                session.expunge(row)


_install_auto_default_space()
