"""T-D0: library browse paths with a Space-restricted caller (1 / 5 / 20 readable scopes) vs the unrestricted legacy answer.

    spikes/library-scale/run.sh bench_spaces.py --label 10k [--runs 7]

Runs the Space-aware LibraryService methods in process against spike_ls_<label> with a hand-built SpaceAccess
(the Space tables are not needed: only the resulting set of readable scopes matters for these paths).
Output: results/api_<label>_spaces.json.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from uuid import UUID, uuid4

import harness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--runs", type=int, default=7)
    args = parser.parse_args()
    harness.ensure_backend_on_path()
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker

    from app.core.scoping import OrganizationScope
    from app.library.models import LibraryNode
    from app.library.service import LibraryService
    from app.spaces.access import SpaceAccess
    from app.workspaces.models import WorkspaceFolder

    engine = create_engine(harness.sa_url(harness.db_name(args.label)))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    statements: list[float] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(time.perf_counter()))
    org = session.scalar(select(LibraryNode.organization_id).limit(1))
    scope = OrganizationScope(org)
    folders = list(session.scalars(select(WorkspaceFolder.id).where(WorkspaceFolder.organization_id == org)))
    root = session.scalar(select(LibraryNode).where(LibraryNode.organization_id == org, LibraryNode.kind == "source"))
    service = LibraryService(session)
    user = uuid4()
    random.seed(7)

    def access(k: int | None) -> SpaceAccess:
        if k is None:
            return SpaceAccess(org, user, {}, {f: frozenset() for f in folders}, unrestricted=True)
        return SpaceAccess(org, user, {}, {f: frozenset() for f in random.sample(folders, k)})

    cases = {
        "roots": lambda a: service.roots(scope=scope, user_id=user, access=a),
        "children_p1": lambda a: service.children(scope=scope, user_id=user, parent_id=root.id, page=1, page_size=100, access=a),
        "children_p5": lambda a: service.children(scope=scope, user_id=user, parent_id=root.id, page=5, page_size=100, access=a),
        "search_ra": lambda a: service.search_page(scope=scope, user_id=user, query="ra", page=1, page_size=50, access=a),
        "mention_ra": lambda a: service.mention_candidates(scope=scope, user_id=user, query="ra", access=a),
    }
    results = []
    for k in (None, 1, 5, min(20, len(folders))):
        a = access(k)
        for name, call in cases.items():
            times, counts = [], []
            call(a)  # warm
            for _ in range(args.runs):
                statements.clear()
                t = time.perf_counter()
                call(a)
                times.append((time.perf_counter() - t) * 1000)
                counts.append(len(statements))
            times.sort()
            results.append({"readable_scopes": "all (legacy)" if k is None else k, "case": name,
                            "median_ms": round(statistics.median(times), 1), "p95_ms": round(times[-1], 1),
                            "statements": counts[-1]})
            print(results[-1])
    out = harness.RESULTS / f"api_{args.label}_spaces.json"
    out.write_text(json.dumps({"label": args.label, "scopes_total": len(folders), "runs": args.runs,
                               "results": results}, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
