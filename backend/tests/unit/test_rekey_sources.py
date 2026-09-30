from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.models import Base
from app.identity.models import User
from app.integrations.google_drive import CredentialCipher, GoogleCredentials
from app.integrations.models import DataSource
from app.library.models import ManualSyncRun  # noqa: F401
from app.organizations.models import Organization
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection
from scripts.rekey_sources import primary_only, rekey


def test_rekey_dry_run_apply_idempotence_and_provider_isolation():
    old, new = [Fernet.generate_key().decode() for _ in range(2)]
    legacy, cipher = CredentialCipher(old), CredentialCipher(new, fallback_keys=[old])
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="owner@example.test")
        org = Organization(name="Acme")
        session.add_all([org, user])
        session.flush()
        sources = [
            DataSource(
                organization_id=org.id,
                connected_by_user_id=user.id,
                provider=provider,
                status="connected",
                encrypted_credentials=enc.encrypt(GoogleCredentials("a", "r", None)),
            )
            for provider, enc in [
                ("notion", legacy),
                ("notion", legacy),
                ("notion", cipher),
                ("google_drive", legacy),
            ]
        ]
        session.add_all(sources)
        session.flush()
        folder = WorkspaceFolder(
            organization_id=org.id,
            source_id=sources[0].id,
            external_folder_id="root",
            name="Docs",
            uniform_access_confirmed=True,
        )
        session.add(folder)
        session.flush()
        selection = WorkspaceFolderSelection(
            workspace_folder_id=folder.id,
            kind="folder",
            external_folder_id=str(uuid4()),
            encrypted_delta_link=legacy.encrypt_cursor("cursor"),
        )
        session.add(selection)
        session.commit()
        before = [s.encrypted_credentials for s in sources]
        old_cursor = selection.encrypted_delta_link
        predicate = primary_only([new])
        assert rekey(
            session, provider="notion", cipher=cipher, is_current=predicate, apply=False
        ) == {"sources": 3, "rotated": 2, "cursors": 1}
        assert (
            before == [s.encrypted_credentials for s in sources]
            and old_cursor == selection.encrypted_delta_link
        )
        assert rekey(
            session, provider="notion", cipher=cipher, is_current=predicate, apply=True
        ) == {"sources": 3, "rotated": 2, "cursors": 1}
        assert all(
            CredentialCipher(new).decrypt(s.encrypted_credentials).access_token == "a"
            for s in sources[:3]
        )
        assert CredentialCipher(new).decrypt_cursor(selection.encrypted_delta_link) == "cursor"
        assert sources[3].encrypted_credentials == before[3]
        assert rekey(
            session, provider="notion", cipher=cipher, is_current=predicate, apply=True
        ) == {"sources": 3, "rotated": 0, "cursors": 0}
    engine.dispose()
