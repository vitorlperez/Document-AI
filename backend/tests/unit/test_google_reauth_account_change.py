"""M55: reconnecting a source with a different Google account must not keep serving the old account's state."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)

from types import SimpleNamespace

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.integrations.google_drive import (
    CredentialCipher,
    GoogleConnectionService,
    GoogleCredentials,
)
from app.workspaces.models import WorkspaceFolderSelection
from tests.sync_helpers import T0, seed, session, space  # noqa: F401


class Port:
    def __init__(self, email: str) -> None:
        self.email = email

    def exchange_code(self, *, code: str) -> GoogleCredentials:
        return GoogleCredentials("access", "refresh", None)

    def account_email(self, *, credentials: GoogleCredentials) -> str:
        return self.email


def reconnect(session, source, user, *, email: str) -> None:
    service = GoogleConnectionService(session, CredentialCipher(Fernet.generate_key().decode()))
    state = SimpleNamespace(source_id=source.id, organization_id=source.organization_id,
                            user_id=user.id, consumed_at=None)
    service._consume_state = lambda **_: state  # the OAuth state handshake is covered elsewhere
    service.complete(raw_state="s", code="c", session_secret="x", port=Port(email))


def test_other_account_resets_delta_cursors_so_the_next_sync_is_complete(session) -> None:
    organization, user, source = seed(session)
    source.account_email = "first@example.test"
    space(session, organization, source, "all", created_at=T0)
    selection = session.scalars(select(WorkspaceFolderSelection)).one()
    selection.encrypted_delta_link = "cursor-of-the-first-account"
    session.flush()

    reconnect(session, source, user, email="second@example.test")

    assert source.account_email == "second@example.test"
    assert selection.encrypted_delta_link is None


def test_same_account_keeps_delta_cursors(session) -> None:
    organization, user, source = seed(session)
    source.account_email = "first@example.test"
    space(session, organization, source, "all", created_at=T0)
    selection = session.scalars(select(WorkspaceFolderSelection)).one()
    selection.encrypted_delta_link = "cursor"
    session.flush()

    reconnect(session, source, user, email="first@example.test")

    assert selection.encrypted_delta_link == "cursor"
