"""List or prune library files that no workspace indexes (no live `documents` row).

Idempotent and local-only (never calls a provider). Dry-run by default.
Run from backend: .venv/bin/python -m scripts.reconcile_library_orphans [--source UUID] [--apply]

After the M55 release the scheduled sync already re-reads these files (Drive/OneDrive/SharePoint)
and prunes the ones the source no longer serves; this command only previews or forces the prune.
"""

import argparse
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import build_engine, build_session_factory
from app.integrations.models import DataSource
from app.library.service import LibraryService


def reconcile(session, *, source_ids: list[UUID] | None = None, apply: bool = False) -> dict[UUID, int]:
    """Orphan count per source; with ``apply`` they are pruned (and their emptied folders)."""
    library = LibraryService(session)
    query = select(DataSource)
    if source_ids:
        query = query.where(DataSource.id.in_(source_ids))
    result: dict[UUID, int] = {}
    for source in session.scalars(query):
        orphans = library.orphan_file_ids(organization_id=source.organization_id, source_id=source.id)
        if apply and orphans:
            library.prune_orphan_file_nodes(organization_id=source.organization_id, source_id=source.id)
        if orphans:
            result[source.id] = len(orphans)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=UUID, help="restrict to a data source")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with build_session_factory(build_engine(get_settings()))() as session:
        found = reconcile(session, source_ids=args.source, apply=args.apply)
        if args.apply:
            session.commit()
        mode = "apply" if args.apply else "dry-run"
        for source_id, count in found.items():
            print(f"{mode}: source {source_id}: {count} orphan file nodes")
        print(f"{mode}: {sum(found.values())} orphan file nodes in {len(found)} sources")


if __name__ == "__main__":
    main()
