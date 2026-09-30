from uuid import uuid4

from app.core.config import Settings
from app.integrations.registry import IntegrationRegistry


def test_google_registry_binds_database_context_for_deltas():
    session, source_id = object(), uuid4()
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    adapter = IntegrationRegistry(settings).get(
        "google_drive", session=session, source_id=source_id
    )
    assert adapter._provider.session is session
    assert adapter._provider.source_id == source_id


def test_all_adapters_accept_known_documents_without_changing_scope():
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    for provider in ("google_drive", "onedrive", "notion"):
        adapter = IntegrationRegistry(settings).get(provider)
        captured = []
        adapter._provider.discover = lambda captured=captured, **kwargs: captured.append(kwargs)
        adapter.discover(
            encrypted_credentials="x", selections=[], known_documents={"f": (None, "indexed")}
        )
        assert captured[0]["encrypted_credentials"] == "x" and captured[0]["selections"] == []


import pytest


@pytest.mark.parametrize('provider', ['google_drive', 'onedrive'])
@pytest.mark.parametrize('enabled', [False, True])
def test_registry_applies_format_flag_to_actual_reader(monkeypatch, provider, enabled):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from cryptography.fernet import Fernet

    from app.integrations.google_drive import CredentialCipher, GoogleCredentials, RemoteFile
    from app.integrations.onedrive import OneDriveCredentials

    key = Fernet.generate_key().decode()
    settings = Settings(database_url='postgresql+psycopg://u:p@localhost/db',
                        google_token_encryption_key=key, microsoft_token_encryption_key=key,
                        new_formats_enabled=enabled)
    adapter = IntegrationRegistry(settings).get(provider)
    reader, calls = adapter._provider, []
    monkeypatch.setattr(reader.client, 'read_file', lambda **kw: (calls.append('read'), b'Approved')[1])
    expiry = datetime.now(UTC)+timedelta(hours=1)
    if provider == 'google_drive':
        monkeypatch.setattr(reader.client,'start_page_token',lambda **kw:'cursor')
        monkeypatch.setattr(reader.client,'list_all_files',lambda **kw:[RemoteFile('f','f.txt','text/plain','https://source.test/f',None)])
        credentials = CredentialCipher(key).encrypt(GoogleCredentials('a','r',expiry))
        selection = SimpleNamespace(id=uuid4(),kind='all_accessible',encrypted_delta_link=None)
        document = adapter.discover(encrypted_credentials=credentials,selections=[selection]).documents[0]
    else:
        document = reader._read_one(OneDriveCredentials('a','r',expiry), {'id':'f','name':'f.txt','file':{'mimeType':'text/plain'}})
    assert calls == (['read'] if enabled else [])
    assert document.text == ('Approved' if enabled else None)
