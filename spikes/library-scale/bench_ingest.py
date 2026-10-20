"""Ingestion-side cost: reconcile() of N discovered documents into one organization (no network, no embeddings).

    ./run.sh bench_ingest.py --steps 500,500,1000,2000,4000

Each step reconciles a FULL snapshot that contains every document seen so far + `step` new ones, so it
shows (1) cost of inserting new docs as the org grows, (2) cost of re-syncing the unchanged ones.
Uses its own scratch database `spike_ls_ing` (recreated each run).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import tracemalloc

import harness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", default="500,500,1000,2000,4000")
    parser.add_argument("--chars", type=int, default=4500)
    args = parser.parse_args()
    steps = [int(x) for x in args.steps.split(",")]

    database = harness.db_name("ing")
    harness.create_db_from_template(database)
    harness.ensure_backend_on_path()
    import importlib
    import os

    os.environ["DATABASE_URL"] = harness.sa_url(database)

    importlib.import_module("app.main")  # registers every mapped model (FKs across modules)
    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.orm import sessionmaker

    from app.audit_usage.service import UsageService  # noqa: F401  (import check)
    from app.core.config import Settings
    from app.core.scoping import OrganizationScope
    from app.identity.models import User
    from app.ingestion.service import DiscoveredDocument, IngestionService
    from app.integrations.models import DataSource
    from app.knowledge.models import Document, DocumentChunk
    from app.organizations.models import Membership, MembershipRole, Organization
    from app.workspaces.models import WorkspaceFolder

    engine = create_engine(harness.sa_url(database))
    stmts = {"n": 0, "ms": 0.0, "t0": 0.0, "shapes": {}}

    @event.listens_for(engine, "before_cursor_execute")
    def _b(conn, cur, statement, params, ctx, many):
        stmts["t0"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _a(conn, cur, statement, params, ctx, many):
        stmts["n"] += 1
        stmts["ms"] += (time.perf_counter() - stmts["t0"]) * 1000
        key = re.sub(r"\s+", " ", re.sub(r"%\(\w+\)s|\$\d+|'[^']*'|\b\d+\b", "?", statement))[:110]
        stmts["shapes"][key] = stmts["shapes"].get(key, 0) + 1

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(database_url=harness.sa_url(database), public_app_url="http://app.example.test", active_document_limit=1_000_000)
    with factory() as session:
        org = Organization(name="Ingest spike")
        user = User(email="ing@spike.example.test")
        session.add_all([org, user])
        session.flush()
        session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.ADMIN, is_active=True))
        source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x", status="connected", connected_by_user_id=user.id)
        session.add(source)
        session.flush()
        folder = WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id="f1", name="Big", uniform_access_confirmed=True)
        session.add(folder)
        session.commit()
        org_id, user_id, folder_id = org.id, user.id, folder.id

    rng = random.Random(3)
    words = ["alpha", "beta", "gamma", "delta", "orbit", "ledger", "invoice", "contract", "quarter", "budget"]

    def make(i: int) -> DiscoveredDocument:
        text = " ".join(rng.choice(words) + str(rng.randrange(1000)) for _ in range(args.chars // 9))
        return DiscoveredDocument(external_file_id=f"ing-{i:07d}", name=f"Doc {i}.txt", mime_type="text/plain",
                                  source_url=f"https://drive.example.test/{i}", text=text)

    rows, total = [], 0
    docs: list = []
    for step in steps:
        new = [make(total + k) for k in range(step)]
        docs.extend(new)
        total += step
        for k in stmts:
            if k != "shapes":
                stmts[k] = 0
        stmts["shapes"] = {}
        with factory() as session:
            service = IngestionService(session, settings=settings)
            job = service.enqueue(scope=OrganizationScope(org_id), user_id=user_id, workspace_folder_id=folder_id)
            tracemalloc.start()
            t = time.perf_counter()
            service.reconcile(job_id=job.id, documents=list(docs))
            session.commit()
            elapsed = time.perf_counter() - t
            _cur, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            active = session.scalar(select(func.count()).select_from(Document).where(Document.organization_id == org_id, Document.index_status == "indexed"))
            chunks = session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.organization_id == org_id))
        top = sorted(stmts["shapes"].items(), key=lambda kv: -kv[1])[:3]
        row = {"step_new_docs": step, "docs_in_snapshot": len(docs), "active_after": active, "chunks_after": chunks,
               "reconcile_s": round(elapsed, 2), "statements": stmts["n"], "sql_s": round(stmts["ms"] / 1000, 2),
               "py_peak_mb": round(peak / 1e6), "top_repeated_statements": [[k, v] for k, v in top]}
        rows.append(row)
        print(json.dumps(row), flush=True)
    (harness.RESULTS / "ingest.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    sys.exit(main())
