import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.models import Base
from app.integrations.google_drive_sa import ServiceAccountKeyCipher
from app.integrations.google_sa_models import GoogleSaIdentity


def pool_module():
    path = Path(__file__).resolve().parents[3] / "scripts/drive_sa_pool.py"
    spec = importlib.util.spec_from_file_location("drive_sa_pool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pool_throttle_and_encrypted_storage():
    module = pool_module()
    import app.identity.models, app.organizations.models, app.integrations.models, app.workspaces.models  # noqa

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    time = [0.0]
    calls = []

    def sleep(seconds):
        time[0] += seconds

    def clock():
        return time[0]

    class Iam:
        def create_robot(self, project, account):
            calls.append(time[0])
            return {
                "client_email": account + "@" + project + ".iam.gserviceaccount.com",
                "private_key": "fake-secret",
                "private_key_id": "key-id",
            }

    cipher = ServiceAccountKeyCipher(Fernet.generate_key().decode())
    with Session(engine) as session:
        assert (
            module.fill_pool(
                session=session,
                project_id="pool-test",
                count=4,
                quota=100,
                iam=Iam(),
                cipher=cipher,
                sleep=sleep,
                clock=clock,
            )
            == 4
        )
        identities = list(session.scalars(select(GoogleSaIdentity)))
        assert all("fake-secret" not in x.encrypted_key for x in identities)
        assert all(
            cipher.decrypt(x.encrypted_key)["private_key"] == "fake-secret" for x in identities
        )
    assert all(sum(start <= x < start + 60 for x in calls) <= 3 for start in calls)
