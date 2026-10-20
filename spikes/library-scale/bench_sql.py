"""Retrieval-path timings: what the app does today vs. the same filters pushed into SQL, by folder-set size.

    ./run.sh bench_sql.py --label 10k [--hnsw]

"Folder set" = the allowed `workspace_folder_id`s (the app's unit of filtering; a Space would be a set of
them). Sizes: 1, 10%, 50% and 100% of the workspaces of the dataset. All statements are timed with the
real SQLAlchemy models/`PgVectorSimilarity` so results include ORM hydration and Python-side cost.
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import time
import tracemalloc

import numpy as np

import harness


def ms(fn, runs=3):
    out, times = None, []
    for _ in range(runs):
        t = time.perf_counter()
        out = fn()
        times.append((time.perf_counter() - t) * 1000)
    return out, round(statistics.median(times), 1), round(min(times), 1)


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # macOS: bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--hnsw", action="store_true", help="build an HNSW index on embedding_vec first (slow, big)")
    parser.add_argument("--skip-orm-load", action="store_true")
    args = parser.parse_args()
    meta = harness.load_meta(args.label)
    harness.ensure_backend_on_path()
    import os

    os.environ["DATABASE_URL"] = harness.sa_url(harness.db_name(args.label))
    from sqlalchemy import create_engine, func, literal_column, select, text
    from sqlalchemy.orm import Session, defer

    from app.core.vector import cosine_similarity_expr
    from app.knowledge.models import Document, DocumentChunk
    from app.knowledge.similarity import PgVectorSimilarity

    engine = create_engine(harness.sa_url(harness.db_name(args.label)), pool_size=2)
    org = meta["organization_id"]
    ws_ids = meta["workspace_ids"]
    W = len(ws_ids)
    centroids = np.load(harness.RESULTS / f"centroids_{args.label}.npy")
    topic = meta["ws_topics"][0][0]
    qv = 0.5 * centroids[topic] + 0.5 * np.random.default_rng(1).standard_normal(1536).astype("float32") / 39.2
    qv = (qv / np.linalg.norm(qv)).tolist()
    qtext = "[" + ",".join(f"{x:.8f}" for x in qv) + "]"

    results = {"label": args.label, "chunks": meta["chunks"], "workspaces": W, "rows": []}

    def add(group, size_name, n_ws, what, median, best, extra=None):
        row = {"group": group, "folder_set": size_name, "workspaces": n_ws, "what": what, "median_ms": median, "min_ms": best}
        row.update(extra or {})
        results["rows"].append(row)
        print(f"{group:<14}{size_name:<8}{what:<52}{median:>10.1f} ms  (min {best:.1f})  {json.dumps(extra or {})}", flush=True)

    if args.hnsw:
        t = time.perf_counter()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text("SET maintenance_work_mem = '1GB'"))
            c.execute(text("SET max_parallel_maintenance_workers = 0"))
            c.execute(text("CREATE INDEX IF NOT EXISTS ix_spike_hnsw ON document_chunks USING hnsw (embedding_vec vector_cosine_ops)"))
            c.execute(text("ANALYZE document_chunks"))
        results["hnsw_build_s"] = round(time.perf_counter() - t, 1)
        with engine.connect() as c:
            results["hnsw_bytes"] = c.execute(text("select pg_relation_size('ix_spike_hnsw')")).scalar()
        print(f"HNSW build: {results['hnsw_build_s']} s, {results['hnsw_bytes']/1e6:.0f} MB", flush=True)

    with engine.connect() as c:
        stat = c.execute(text("select word, ndoc from ts_stat('select search_vector from document_chunks tablesample system (1)') order by ndoc desc")).all()
    common_words = [w for w, _n in stat[5:8]]  # skip the very top (nearly every chunk)
    rare_word = next(w for w, n in reversed(stat) if n >= 2)
    results["fts_terms"] = {"common": common_words, "rare": rare_word}
    print("fts terms", results["fts_terms"], flush=True)

    sizes = [("1", 1), ("10%", max(1, round(W * 0.1))), ("50%", max(1, W // 2)), ("100%", W)]
    seen = set()
    for size_name, n in sizes:
        if n in seen:
            continue
        seen.add(n)
        folder_ids = ws_ids[:n]
        with Session(engine) as session:
            filters = [
                Document.organization_id == org,
                Document.workspace_folder_id.in_(folder_ids),
                Document.index_status == "indexed",
                DocumentChunk.organization_id == org,
                DocumentChunk.workspace_folder_id.in_(folder_ids),
                DocumentChunk.workspace_folder_id == Document.workspace_folder_id,
                DocumentChunk.embedding.is_not(None),
                DocumentChunk.embedding_model == "text-embedding-3-small",
            ]
            n_chunks = session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.workspace_folder_id.in_(folder_ids)))

            # (a) today: indexed_chunk_count (QuestionService.ask: count over the scoped chunks)
            val, med, best = ms(lambda: session.scalar(
                select(func.count(DocumentChunk.id)).join(Document, Document.id == DocumentChunk.document_id)
                .where(*filters[:3], *filters[3:6])))
            add("app", size_name, n, "count(chunks) in scope [questions.py:1164]", med, best, {"chunks_in_scope": val})

            # (b) today: scoped_rows = every (Document, DocumentChunk) of the scope, vectors deferred
            if not args.skip_orm_load:
                def load():
                    return list(session.execute(
                        select(Document, DocumentChunk).join(DocumentChunk, DocumentChunk.document_id == Document.id)
                        .where(*filters).options(defer(DocumentChunk.embedding), defer(DocumentChunk.embedding_vec))).all())
                tracemalloc.start()
                base_rss = rss_mb()
                t = time.perf_counter()
                rows = load()
                load_ms = (time.perf_counter() - t) * 1000
                cur, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                add("app", size_name, n, "scoped_rows ORM load (1 run) [questions.py:1202]", round(load_ms, 1), round(load_ms, 1),
                    {"rows": len(rows), "py_heap_mb": round(cur / 1e6), "py_peak_mb": round(peak / 1e6), "rss_mb_after": round(rss_mb())})
                # (c) today: similarity scores for ALL chunks in scope, dict back in Python
                sim = PgVectorSimilarity()
                def scores():
                    return sim.scores(session, filters=filters, question_embedding=qv, rows=rows)
                val, med, best = ms(scores, runs=2)
                add("app", size_name, n, "PgVectorSimilarity.scores = all chunks [similarity.py:30]", med, best, {"scores_returned": len(val)})
                del rows
            else:
                sim = PgVectorSimilarity()
                val, med, best = ms(lambda: sim.scores(session, filters=filters, question_embedding=qv, rows=[]), runs=2)
                add("app", size_name, n, "PgVectorSimilarity.scores = all chunks [similarity.py:30]", med, best, {"scores_returned": len(val)})

            # (d) proposal: top-K inside SQL with the same filters (exact scan unless an HNSW index exists)
            dist = literal_column(f"(document_chunks.embedding_vec <=> '{qtext}'::vector)")
            score = literal_column(f"1 - (document_chunks.embedding_vec <=> '{qtext}'::vector)")
            topk = (select(DocumentChunk.id, score).join(Document, Document.id == DocumentChunk.document_id)
                    .where(*filters, DocumentChunk.embedding_vec.is_not(None)).order_by(dist).limit(100))
            val, med, best = ms(lambda: session.execute(topk).all())
            add("topk-sql", size_name, n, "ORDER BY <=> LIMIT 100 (exact, current indexes)", med, best, {"returned": len(val)})
            # (e) lean variant: no join to documents, only chunk columns (org+folder)
            lean = (select(DocumentChunk.id, score).where(
                DocumentChunk.organization_id == org, DocumentChunk.workspace_folder_id.in_(folder_ids),
                DocumentChunk.embedding_vec.is_not(None)).order_by(dist).limit(100))
            val, med, best = ms(lambda: session.execute(lean).all())
            add("topk-sql", size_name, n, "same, chunk-only filter (no documents join)", med, best, {"returned": len(val)})
            if args.hnsw:
                fl = "{" + ",".join(folder_ids) + "}"
                sql = (f"SELECT id FROM document_chunks WHERE organization_id = '{org}' AND workspace_folder_id = ANY('{fl}'::uuid[]) "
                       f"AND embedding_vec IS NOT NULL ORDER BY embedding_vec <=> '{qtext}'::vector LIMIT 100")
                with engine.connect() as c:
                    c.execute(text("SET hnsw.ef_search = 100"))
                    c.execute(text("SET hnsw.iterative_scan = relaxed_order"))
                    c.execute(text("SET hnsw.max_scan_tuples = 200000"))
                    val, med, best = ms(lambda: c.execute(text(sql)).all())
                    got = {r[0] for r in val}
                    c.execute(text("SET enable_indexscan = off"))
                    exact = {r[0] for r in c.execute(text(sql)).all()}
                    c.execute(text("SET enable_indexscan = on"))
                    add("hnsw", size_name, n, "chunk-only filter + HNSW iterative scan (ef_search=100)", med, best,
                        {"returned": len(val), "recall_at_100_vs_exact": round(len(got & exact) / max(1, len(exact)), 3)})
                    plan = "\n".join(r[0] for r in c.execute(text("EXPLAIN (ANALYZE, COSTS OFF) " + sql)))
                    results.setdefault("hnsw_plans", {})[size_name] = plan[:1800]
                    c.rollback()

            # (f) FTS the way RetrievalService.search does it, scoped by the folder set
            ts = func.to_tsquery("simple", " | ".join(common_words))
            vec = literal_column("document_chunks.search_vector")
            fts = (select(Document.id, func.ts_rank_cd(vec, ts).label("r")).join(DocumentChunk, DocumentChunk.document_id == Document.id)
                   .where(Document.organization_id == org, Document.workspace_folder_id.in_(folder_ids), Document.index_status == "indexed",
                          DocumentChunk.organization_id == org, DocumentChunk.workspace_folder_id.in_(folder_ids), vec.op("@@")(ts))
                   .order_by(literal_column("r").desc()).limit(100))
            val, med, best = ms(lambda: session.execute(fts).all())
            add("fts", size_name, n, "FTS common terms top-100 [retrieval.py:75]", med, best, {"returned": len(val)})
            ts2 = func.to_tsquery("simple", rare_word)
            fts2 = (select(Document.id).join(DocumentChunk, DocumentChunk.document_id == Document.id)
                    .where(Document.organization_id == org, Document.workspace_folder_id.in_(folder_ids), Document.index_status == "indexed",
                           DocumentChunk.organization_id == org, DocumentChunk.workspace_folder_id.in_(folder_ids), vec.op("@@")(ts2)).limit(100))
            val, med, best = ms(lambda: session.execute(fts2).all())
            add("fts", size_name, n, "FTS rare term", med, best, {"returned": len(val)})

    # (h) the library tree, service level: a synthetic flat folder with 5000 files (rolled back afterwards),
    #     deep OFFSET pages, plus the whole-org node load the catalog/mention paths do (_selection_nodes).
    from uuid import UUID, uuid4

    from app.core.scoping import OrganizationScope
    from app.library.models import LibraryNode
    from app.library.service import LibraryService

    scope = OrganizationScope(UUID(org))
    owner = UUID(meta["owner_user_id"])
    with Session(engine) as session:
        flat = uuid4()
        top0 = UUID(meta["workspace_root_nodes"][0])
        src = session.scalar(select(LibraryNode.source_id).where(LibraryNode.id == top0))
        session.add(LibraryNode(id=flat, organization_id=scope.organization_id, source_id=src, parent_id=top0, external_id="spike-flat",
                                kind="folder", name="ZZ flat 5000"))
        session.flush()
        file_ids = [r[0] for r in session.execute(select(LibraryNode.id).where(
            LibraryNode.organization_id == scope.organization_id, LibraryNode.kind == "file").limit(5000)).all()]
        session.execute(text("update library_nodes set parent_id=:p where id = ANY(:ids)").bindparams(p=flat, ids=file_ids))
        session.flush()
        svc = LibraryService(session)
        for page in (1, 25, 50):
            def run(page=page):
                res = svc.children(scope=scope, user_id=owner, parent_id=flat, page=page, page_size=100)
                svc.documents_and_indexing_for_nodes(scope=scope, nodes=res.items)
                return res
            res, med, best = ms(run)
            add("tree", "flat5000", 0, f"children(flat folder 5000 files) page {page}/50 (+documents lookup)", med, best, {"items": len(res.items), "total": res.total})
        def load_all():
            return svc._selection_nodes(scope=scope)
        nodes, med, best = ms(load_all, runs=2)
        add("tree", "all", 0, "_selection_nodes: ORM-load every node of the org [library/service.py:985]", med, best, {"nodes": len(nodes)})
        def cat():
            return svc.authorized_catalog(scope=scope, user_id=owner, providers=["google_drive"], mentions=[])
        c, med, best = ms(cat, runs=2)
        add("tree", "all", 0, "authorized_catalog(no mentions) [library/service.py:1002]", med, best, {"allowed": len(c.nodes)})
        def under():
            return svc.indexed_documents_under(scope=scope, user_id=owner, node_id=UUID(meta["source_root_node_id"]), allow_source=True)
        d, med, best = ms(under, runs=2)
        add("tree", "all", 0, "indexed_documents_under(source root) [library/service.py:256]", med, best, {"docs": len(d)})
        # DB-side alternative: one recursive CTE for the subtree files + their indexed documents
        cte = text("""
            with recursive sub as (
              select id, kind, external_id, source_id from library_nodes where id = :root
              union all
              select n.id, n.kind, n.external_id, n.source_id from library_nodes n join sub s on n.parent_id = s.id
            )
            select count(*) from sub where kind = 'file'""")
        v, med, best = ms(lambda: session.execute(cte, {"root": UUID(meta["source_root_node_id"])}).scalar())
        add("tree", "all", 0, "recursive CTE: subtree files of the source root", med, best, {"files": v})
        session.rollback()

    # (g) document-id filter (mentions): IN-list size vs the 65535 bind-parameter ceiling
    with Session(engine) as session:
        ids = [r[0] for r in session.execute(select(Document.id).where(Document.organization_id == org, Document.index_status == "indexed")).all()]
        results["indexed_ids"] = len(ids)
        for k in (1000, 10000, 30000, 60000, 70000):
            if k > len(ids):
                continue
            sub = ids[:k]
            try:
                val, med, best = ms(lambda: session.scalar(select(func.count()).select_from(Document).where(Document.id.in_(sub))), runs=2)
                add("doc-in", f"{k}", 0, f"Document.id IN ({k} binds)", med, best, {"count": val})
            except Exception as error:  # noqa: BLE001
                add("doc-in", f"{k}", 0, f"Document.id IN ({k} binds) FAILED", 0, 0, {"error": f"{type(error).__name__}: {str(error)[:120]}"})
                session.rollback()
            try:
                val, med, best = ms(lambda: session.scalar(text("select count(*) from documents where id = ANY(:ids)").bindparams(ids=sub)), runs=2)
                add("doc-in", f"{k}", 0, f"documents.id = ANY(array of {k})", med, best, {"count": val})
            except Exception as error:  # noqa: BLE001
                add("doc-in", f"{k}", 0, f"= ANY(array {k}) FAILED", 0, 0, {"error": f"{type(error).__name__}: {str(error)[:120]}"})
                session.rollback()

    with Session(engine) as session:
        ids = [r[0] for r in session.execute(select(Document.id).where(Document.organization_id == org, Document.index_status == "indexed")).all()]
        for k in (20000, 33000, 40000):
            if 2 * k > len(ids) * 2:
                continue
            a, b = ids[:k], ids[:k]
            try:
                n = session.scalar(select(func.count()).select_from(Document).where(Document.id.in_(a), Document.id.in_(b)))
                add("doc-in", f"2x{k}", 0, f"two IN lists of {k} binds (= {2*k} params; lexical query shape, questions.py:1405)", 0, 0, {"count": n, "ok": True})
            except Exception as error:  # noqa: BLE001
                add("doc-in", f"2x{k}", 0, f"two IN lists of {k} binds (= {2*k} params) FAILED", 0, 0, {"error": f"{type(error).__name__}: {str(error)[:140]}"})
                session.rollback()

    (harness.RESULTS / f"sql_{args.label}{'_hnsw' if args.hnsw else ''}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    sys.exit(main())
