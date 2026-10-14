"""Real PostgreSQL migrations, permanent assignments and concurrent pool claims."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.google_drive_sa_service import DriveSaConnectionService
from app.integrations.google_sa_models import GoogleSaIdentity, GoogleSaProject
from app.organizations.models import Membership, MembershipRole, Organization

pytestmark = pytest.mark.postgres
BACKEND = Path(__file__).resolve().parents[2]


def alembic(url, *args):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=os.environ | {"DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_migration_pool_claims_and_never_recycle(test_database_url):
    alembic(test_database_url, "downgrade", "base")
    alembic(test_database_url, "upgrade", "head")
    engine = create_engine(test_database_url)
    assert "last_reconciled_at" in {
        x["name"] for x in inspect(engine).get_columns("drive_folder_links")
    }
    settings = Settings(
        database_url=test_database_url,
        google_drive_sa_enabled=True,
        google_sa_key_encryption_key=Fernet.generate_key().decode(),
        _env_file=None,
    )
    with Session(engine) as session:
        user = User(email=f"m58-owner-{uuid4()}@example.test")
        orgs = [Organization(name="m58-A"), Organization(name="m58-B")]
        session.add_all([user, *orgs])
        session.flush()
        for org in orgs:
            session.add(
                Membership(
                    organization_id=org.id,
                    user_id=user.id,
                    role=MembershipRole.OWNER,
                    is_active=True,
                )
            )
        project = GoogleSaProject(gcp_project_id="m58-pool")
        session.add(project)
        session.flush()
        for n in range(2):
            session.add(
                GoogleSaIdentity(
                    project_id=project.id,
                    sa_email=f"m58-{n}@example.test",
                    encrypted_key="encrypted",
                )
            )
        session.commit()
        user_id = user.id
        project_id = project.id
        org_ids = [x.id for x in orgs]
    barrier = Barrier(2)

    def enable(org_id):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            source = DriveSaConnectionService(session, settings).enable(
                scope=OrganizationScope(org_id), user_id=user_id
            )
            result = source.id, source.sa_identity_id
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(enable, org_ids))
    assert claims[0][1] != claims[1][1]
    # Concurrent enable calls for one organization must consume only one robot.
    with Session(engine) as session:
        org = Organization(name="m58-C")
        session.add(org)
        session.flush()
        session.add(
            Membership(
                organization_id=org.id, user_id=user_id, role=MembershipRole.OWNER, is_active=True
            )
        )
        for n in range(2):
            session.add(
                GoogleSaIdentity(
                    project_id=project_id,
                    sa_email=f"m58-new-{n}@example.test",
                    encrypted_key="encrypted",
                )
            )
        session.commit()
        same_org_id = org.id
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        same_claims = list(executor.map(enable, [same_org_id, same_org_id]))
    assert same_claims[0] == same_claims[1]
    with Session(engine) as session:
        identity = session.get(GoogleSaIdentity, claims[0][1])
        identity.status = "retired"
        session.commit()
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE google_sa_identities SET organization_id=:other,status='assigned' WHERE id=:id"
                ),
                {"other": org_ids[1], "id": identity.id},
            )
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE google_sa_identities SET organization_id=NULL,status='free',assigned_at=NULL WHERE id=:id"
                ),
                {"id": identity.id},
            )
        session.rollback()
        assert session.get(GoogleSaIdentity, claims[0][1]).status == "retired"
    engine.dispose()
    alembic(test_database_url, "downgrade", "20261013_0031")
    alembic(test_database_url, "upgrade", "head")


def test_on_demand_concurrency_one_robot_per_org(test_database_url):
    """Duplicate enable/provision calls for one org create one robot; distinct orgs get distinct ones."""
    from threading import Barrier

    from sqlalchemy import func, select

    from app.integrations.google_drive_sa import ServiceAccountKeyCipher
    from app.integrations.google_sa_provisioner import ProvisionerRetry, RobotProvisioner
    from app.integrations.models import DataSource

    alembic(test_database_url, "downgrade", "base")
    alembic(test_database_url, "upgrade", "head")
    engine = create_engine(test_database_url)
    key = Fernet.generate_key().decode()
    settings = Settings(
        database_url=test_database_url,
        google_drive_sa_enabled=True,
        google_sa_key_encryption_key=key,
        google_sa_pool_projects="od-pool-a,od-pool-b",
        _env_file=None,
    )
    with Session(engine) as session:
        user = User(email=f"m58-od-{uuid4()}@example.test")
        orgs = [Organization(name=f"od-{n}") for n in range(3)]
        session.add_all([user, *orgs])
        session.flush()
        for org in orgs:
            session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER, is_active=True))
        session.commit()
        user_id, org_ids = user.id, [x.id for x in orgs]

    created = []

    class Iam:
        def create_account(self, project, account_id, name):
            created.append(account_id)
            return f"{account_id}@{project}.iam.gserviceaccount.com"

        def create_key(self, email):
            return {"client_email": email, "private_key": "pem", "private_key_id": "k"}

    def enable(org_id, barrier):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            service = DriveSaConnectionService(session, settings)
            source = service.enable(scope=OrganizationScope(org_id), user_id=user_id)
            result = (source.id, service.needs_provisioning)
            session.commit()
            return result

    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        same = list(executor.map(lambda org: enable(org, barrier), [org_ids[0], org_ids[0]]))
    assert same[0][0] == same[1][0]
    assert sorted(x[1] for x in same) == [False, True]  # exactly one dispatch decision
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DataSource).where(DataSource.organization_id == org_ids[0])) == 1

    def provision(source_id, barrier):
        with Session(engine) as session:
            worker = RobotProvisioner(session, settings, Iam(), ServiceAccountKeyCipher(key))
            barrier.wait(timeout=10)
            try:
                return worker.provision_source(source_id)
            except ProvisionerRetry:
                session.rollback()
                return "retry"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: provision(same[0][0], Barrier(1)), range(2)))
    assert "ready" in results
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(GoogleSaIdentity).where(GoogleSaIdentity.organization_id == org_ids[0])) == 1
    assert len(created) == 1

    # Different organizations in parallel receive different robots (pool-b absorbs the project lock).
    with Session(engine) as session:
        sources = []
        for org_id in org_ids[1:]:
            source = DriveSaConnectionService(session, settings).enable(scope=OrganizationScope(org_id), user_id=user_id)
            sources.append(source.id)
        session.commit()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda sid: provision(sid, barrier), sources))
    for _ in range(3):
        for index, outcome in enumerate(results):
            if outcome == "retry":  # throttled/locked project: the Celery retry path
                import time

                time.sleep(21)
                results[index] = provision(sources[index], Barrier(1))
    assert results == ["ready", "ready"]
    with Session(engine) as session:
        emails = set(session.scalars(select(GoogleSaIdentity.sa_email).where(GoogleSaIdentity.organization_id.in_(org_ids))))
        assert len(emails) == 3
