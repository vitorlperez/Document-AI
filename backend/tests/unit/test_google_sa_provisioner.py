"""M58 on-demand robots with IAM fully mocked."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import AuditLog
from app.core.config import Settings
from app.core.models import Base
from app.identity.models import User
from app.ingestion import tasks
from app.integrations.google_drive_sa import ServiceAccountKeyCipher
from app.integrations.google_sa_models import GoogleSaIdentity, GoogleSaProject
from app.integrations.google_sa_provisioner import (
    ProvisionerFatal,
    ProvisionerRetry,
    RobotProvisioner,
    robot_account_id,
)
from app.integrations.models import DataSource
from app.organizations.models import Organization


class FakeIam:
    def __init__(self, fail_key=None):
        self.accounts, self.keys, self.deleted, self.fail_key = [], [], [], list(fail_key or [])

    def create_account(self, project, account_id, name):
        self.accounts.append((project, account_id, name))
        return f"{account_id}@{project}.iam.gserviceaccount.com"

    def create_key(self, email):
        if self.fail_key:
            raise self.fail_key.pop(0)
        self.keys.append(email)
        return {"client_email": email, "private_key": "secret-pem", "private_key_id": "kid"}

    def delete_key(self, email, key_id):
        self.deleted.append((email, key_id))


@pytest.fixture
def env():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    key = Fernet.generate_key().decode()
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        google_drive_sa_enabled=True,
        google_sa_key_encryption_key=key,
        google_sa_pool_projects="pool-a,pool-b",
        google_sa_project_quota=2,
        google_sa_warm_pool_size=2,
        _env_file=None,
    )
    with Session(engine) as session:
        yield session, settings, key


def make_source(session, status="provisioning"):
    org, user = Organization(name="o" + uuid4().hex[:6]), User(email=f"{uuid4().hex}@example.test")
    session.add_all([org, user])
    session.flush()
    source = DataSource(
        organization_id=org.id, provider="google_drive_sa", status=status, connected_by_user_id=user.id
    )
    session.add(source)
    session.commit()
    return source


def provisioner(env, iam, clock=None):
    session, settings, key = env
    return RobotProvisioner(session, settings, iam, ServiceAccountKeyCipher(key), now=clock)


def test_account_id_deterministic_and_not_guessable():
    org = uuid4()
    assert robot_account_id("k1", org) == robot_account_id("k1", org)
    assert robot_account_id("k1", org) != robot_account_id("k2", org)
    assert robot_account_id("k1", org) != robot_account_id("k1", uuid4())
    assert len(robot_account_id("k1", org)) <= 30 and robot_account_id("k1", org).startswith("arq-")


def test_provision_creates_dedicated_robot_encrypted_with_audit(env):
    session, _, key = env
    source = make_source(session)
    iam = FakeIam()
    assert provisioner(env, iam).provision_source(source.id) == "ready"
    session.refresh(source)
    identity = session.get(GoogleSaIdentity, source.sa_identity_id)
    assert (source.status, source.account_email) == ("awaiting_share", identity.sa_email)
    assert (identity.status, identity.organization_id) == ("assigned", source.organization_id)
    assert "secret-pem" not in identity.encrypted_key
    assert ServiceAccountKeyCipher(key).decrypt(identity.encrypted_key)["private_key"] == "secret-pem"
    project, account, name = iam.accounts[0]
    assert project == "pool-a" and str(source.organization_id) in name
    actions = list(session.scalars(select(AuditLog.action).where(AuditLog.organization_id == source.organization_id)))
    assert actions == ["drive_sa.robot_provisioned"]


def test_provision_is_idempotent_one_robot_per_org(env):
    session, _, _ = env
    source = make_source(session)
    iam = FakeIam()
    worker = provisioner(env, iam)
    assert worker.provision_source(source.id) == "ready"
    assert worker.provision_source(source.id) == "ready"
    assert len(iam.accounts) == 1
    assert session.scalar(select(GoogleSaIdentity.id).where(GoogleSaIdentity.organization_id == source.organization_id))


def test_different_orgs_get_different_robots(env):
    session, _, _ = env
    first, second = make_source(session), make_source(session)
    iam = FakeIam()
    worker = provisioner(env, iam)
    worker.provision_source(first.id)
    session.get(GoogleSaProject, session.scalar(select(GoogleSaProject.id))).last_iam_create_at = None
    worker.provision_source(second.id)
    session.refresh(first), session.refresh(second)
    assert first.sa_identity_id != second.sa_identity_id
    assert first.account_email != second.account_email


def test_throttle_asks_to_retry_then_proceeds(env):
    session, _, _ = env
    first, second, third = (make_source(session) for _ in range(3))
    now = [datetime(2026, 10, 14, tzinfo=UTC)]
    iam = FakeIam()
    worker = provisioner(env, iam, clock=lambda: now[0])
    worker.provision_source(first.id)
    # pool-b is free for the second org, but pool-a is inside its 20.1 s window afterwards
    worker.provision_source(second.id)
    assert {a[0] for a in iam.accounts} == {"pool-a", "pool-b"}
    with pytest.raises(ProvisionerRetry):
        worker.provision_source(third.id)
    now[0] += timedelta(seconds=21)
    assert worker.provision_source(third.id) == "ready"


def test_capacity_exhausted_is_fatal_and_marks_failed(env):
    session, settings, _ = env
    settings.google_sa_pool_projects = "pool-a"
    for _ in range(2):  # quota 2 per project
        project = session.scalar(select(GoogleSaProject)) or GoogleSaProject(gcp_project_id="pool-a", sa_quota=2)
        session.add(project)
        session.flush()
        other = make_source(session)
        session.add(GoogleSaIdentity(project_id=project.id, sa_email=f"{uuid4().hex}@x.test", encrypted_key="k",
                                     status="assigned", organization_id=other.organization_id,
                                     assigned_at=datetime.now(UTC)))
        session.commit()
    source = make_source(session)
    assert tasks.run_provisioning(session, settings, source.id, provisioner=provisioner(env, FakeIam())) == "failed"
    session.refresh(source)
    assert source.status == "provisioning_failed"


def test_propagation_error_retries_and_failed_key_leaves_no_identity(env):
    session, _, _ = env
    source = make_source(session)
    iam = FakeIam(fail_key=[ProvisionerRetry("org_policy_propagating", 45)])
    worker = provisioner(env, iam)
    with pytest.raises(ProvisionerRetry):
        worker.provision_source(source.id)
    session.rollback()
    assert session.scalar(select(GoogleSaIdentity.id)) is None
    iam.fail_key.clear()
    assert worker.provision_source(source.id) == "ready"


def test_warm_pool_tops_up_and_enable_claims_it(env):
    session, _, _ = env
    worker = provisioner(env, FakeIam())
    assert worker.top_up_warm() >= 1  # throttle may stop early, never exceeds the size
    free = list(session.scalars(select(GoogleSaIdentity).where(GoogleSaIdentity.status == "free")))
    assert all(x.organization_id is None and x.encrypted_key for x in free)
    source = make_source(session)
    assert worker.provision_source(source.id) == "ready"
    session.refresh(source)
    assert source.sa_identity_id in {x.id for x in free}


def test_pool_tick_requeues_stale_provisioning_and_alerts(env):
    session, settings, _ = env
    source = make_source(session)
    sent = []
    result = tasks.drive_sa_pool_tick(
        session=session, settings=settings, send_task=lambda name, args: sent.append((name, args)),
        provisioner=provisioner(env, FakeIam()), now=datetime.now(UTC) + timedelta(minutes=11))
    assert sent == [("document_intelligence.ingestion.provision_drive_sa_robot", [str(source.id)])]
    assert result["requeued"] == 1


def test_capacity_low_alert(env, monkeypatch):
    _, settings, _ = env
    settings.google_sa_capacity_alert_below = 10
    events = []
    from app.integrations import google_sa_provisioner

    class Spy:
        def warning(self, message, extra=None):
            events.append(extra["event"])

        error = warning

    monkeypatch.setattr(google_sa_provisioner, "logger", Spy())
    assert provisioner(env, FakeIam()).check_capacity() == 4
    assert events == ["drive_sa.capacity_low"]


def test_fatal_credential_error_marks_failed(env):
    session, settings, _ = env
    source = make_source(session)

    class Broken(FakeIam):
        def create_account(self, *a):
            raise ProvisionerFatal("provisioner_forbidden")

    assert tasks.run_provisioning(session, settings, source.id, provisioner=provisioner(env, Broken())) == "failed"
    session.refresh(source)
    assert source.status == "provisioning_failed"
