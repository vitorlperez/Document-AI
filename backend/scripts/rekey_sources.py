"""Rotate one provider's credentials/cursors; dry-run unless --apply is passed.

Migration: configure the new provider key on API and worker, with legacy fallback
true; deploy; run dry-run, then --apply; repeat and require zero pending rotations;
set NOTION_TOKEN_ENCRYPTION_LEGACY_FALLBACK=false and redeploy. Rollback: enable
fallback again while retaining the current and legacy keys. Rotate annually.
Never print keys, tokens, credentials or cursor URLs.
"""

import argparse
from collections.abc import Callable, Sequence

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine, build_session_factory
from app.integrations.google_drive import CredentialCipher
from app.integrations.models import DataSource
from app.integrations.onedrive import OneDriveCipher
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection


def rekey(
    session: Session, *, provider: str, cipher, is_current: Callable[[str], bool], apply: bool
) -> dict[str, int]:
    counts = {"sources": 0, "rotated": 0, "cursors": 0}
    query = select(DataSource).where(DataSource.provider == provider)
    if apply:
        query = query.with_for_update()
    sources = list(session.scalars(query))
    for source in sources:
        if not source.encrypted_credentials:
            continue
        counts["sources"] += 1
        if not is_current(source.encrypted_credentials):
            # Validate legacy tokens even in dry-run; broken keys must fail before deployment.
            rotated = cipher.rotate(source.encrypted_credentials)
            counts["rotated"] += 1
            if apply:
                source.encrypted_credentials = rotated
    folder_ids = select(WorkspaceFolder.id).where(
        WorkspaceFolder.source_id.in_([s.id for s in sources])
    )
    query = select(WorkspaceFolderSelection).where(
        WorkspaceFolderSelection.workspace_folder_id.in_(folder_ids),
        WorkspaceFolderSelection.encrypted_delta_link.is_not(None),
    )
    if apply:
        query = query.with_for_update()
    for selection in session.scalars(query):
        if not is_current(selection.encrypted_delta_link):
            rotated = cipher.rotate(selection.encrypted_delta_link)
            counts["cursors"] += 1
            if apply:
                selection.encrypted_delta_link = rotated
    if apply:
        session.commit()
    return counts


def primary_only(keys: Sequence[str | None]) -> Callable[[str], bool]:
    if not keys or not keys[0]:
        raise ValueError("primary provider encryption key is required")
    fernet = Fernet(keys[0].encode())

    def is_current(value: str) -> bool:
        try:
            fernet.decrypt(value.encode())
            return True
        except InvalidToken:
            return False

    return is_current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("google_drive", "onedrive", "notion"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    keys = settings.cipher_keys(args.provider)
    current = primary_only(keys)
    cipher_class = OneDriveCipher if args.provider == "onedrive" else CredentialCipher
    cipher = cipher_class(keys[0], fallback_keys=keys[1:])
    engine = build_engine(settings)
    try:
        with build_session_factory(engine)() as session:
            try:
                counts = rekey(
                    session,
                    provider=args.provider,
                    cipher=cipher,
                    is_current=current,
                    apply=args.apply,
                )
            except (SQLAlchemyError, InvalidToken, ValueError, RuntimeError):
                session.rollback()
                raise SystemExit(
                    "rekey failed; transaction rolled back (check provider key configuration)"
                ) from None
            print(counts)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
