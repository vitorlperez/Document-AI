"""Cost of restricting the library tree and the pgvector/FTS search to an ALLOWED SET OF LIBRARY FOLDERS.

    ./run.sh bench_filter.py --label 50k

Models the "Espaços com acesso por pessoa" read path: a person may see only the subtrees under K folder nodes.
For several selectivities (share of the org's documents the person can see) it measures:

  tree   : visible-subtree resolution with a recursive CTE (descendants) and the ancestor chain (so the
           breadcrumbs render), vs. the Python level-by-level walk the app does today
  search : pgvector top-100 under the visibility filter, three shapes
           (a) one SQL: recursive CTE joined to documents/chunks   (planner decides, HNSW if present)
           (b) two steps: resolve visible document ids first, then `document_id = ANY(:ids)`
           (c) workspace_folder_id = ANY(...) when the allowed set is a union of whole sync scopes
           with exact result (index scan off) as ground truth -> recall@100
  fts    : same visibility filter on the GIN full-text index

Requires the HNSW index (`ix_spike_hnsw`) to compare ANN vs exact; without it only the exact path is measured.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict

import numpy as np

import harness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warm", action="store_true", help="one untimed call before each timed series (page cache warm)")
    args = parser.parse_args()
    meta = harness.load_meta(args.label)
    import psycopg

    conn = psycopg.connect(harness.dsn(harness.db_name(args.label)), autocommit=True)
    org = meta["organization_id"]
    source = meta["source_id"]
    cur = conn.cursor()
    has_hnsw = cur.execute("select count(*) from pg_indexes where indexname='ix_spike_hnsw'").fetchone()[0] == 1
    centroids = np.load(harness.RESULTS / f"centroids_{args.label}.npy")
    topic = meta["ws_topics"][0][0]
    qv = 0.5 * centroids[topic] + 0.5 * np.random.default_rng(1).standard_normal(1536).astype("float32") / 39.2
    qv = qv / np.linalg.norm(qv)
    qtext = "[" + ",".join(f"{x:.8f}" for x in qv.tolist()) + "]"

    nodes = cur.execute("select id, parent_id, kind from library_nodes where organization_id=%s", (org,)).fetchall()
    children = defaultdict(list)
    kind = {}
    for nid, pid, k in nodes:
        kind[nid] = k
        if pid is not None:
            children[pid].append(nid)
    files_below: dict = {}

    def count_files(nid):
        if nid in files_below:
            return files_below[nid]
        total = 1 if kind[nid] == "file" else 0
        for c in children.get(nid, []):
            total += count_files(c)
        files_below[nid] = total
        return total

    import sys as _s

    _s.setrecursionlimit(10000)
    root = next(n for n, p, k in nodes if k == "source")
    count_files(root)
    folders = [n for n, p, k in nodes if k == "folder" and p is not None and p != root and files_below[n] > 0]
    total_files = files_below[root]

    def pick_allowed(share: float, seed: int = 11) -> tuple[list, int]:
        """Disjoint random folders whose subtrees add up to ~share of all files (several small roots, like a real person)."""
        rng = random.Random(seed)
        target = max(1, int(total_files * share))
        chosen, covered, taken = [], 0, set()
        pool = folders[:]
        rng.shuffle(pool)
        cap = max(5, int(target * 0.35))  # no single huge folder: keep the set fragmented
        pid = {n: p for n, p, _k in nodes}
        for f in pool:
            size = files_below[f]
            if size > cap or covered + size > target * 1.1:
                continue
            anc, cur_n, nested = set(), pid.get(f), False
            while cur_n is not None:
                if cur_n in taken:
                    nested = True
                    break
                cur_n = pid.get(cur_n)
            if nested or any(c in taken for c in children.get(f, [])):
                continue
            chosen.append(f)
            taken.add(f)
            covered += size
            if covered >= target:
                break
        return chosen, covered

    def timed(fn, runs=args.runs):
        times, out = [], None
        if args.warm:
            fn()
        for _ in range(runs):
            t = time.perf_counter()
            out = fn()
            times.append((time.perf_counter() - t) * 1000)
        return out, round(statistics.median(times), 1), round(min(times), 1)

    results = {"label": args.label, "total_files": total_files, "hnsw": has_hnsw, "rows": []}

    def add(share, what, med, best, extra=None):
        row = {"share": share, "what": what, "median_ms": med, "min_ms": best, **(extra or {})}
        results["rows"].append(row)
        print(f"{share:<7}{what:<64}{med:>10.1f} ms (min {best:.1f}) {json.dumps(extra or {})}", flush=True)

    if has_hnsw:
        cur.execute("SET hnsw.ef_search = 100")
        cur.execute("SET hnsw.iterative_scan = relaxed_order")
        cur.execute("SET hnsw.max_scan_tuples = 200000")

    for share in (0.002, 0.02, 0.10, 0.50):
        roots, covered = pick_allowed(share)
        label = f"{share*100:g}%"
        info = {"roots": len(roots), "files": covered}
        # --- tree ------------------------------------------------------------------------------
        down = """with recursive sub as (select id from library_nodes where id = ANY(%s)
                  union all select n.id from library_nodes n join sub s on n.parent_id = s.id)
                  select count(*) from sub s join library_nodes f on f.id = s.id where f.kind='file'"""
        v, med, best = timed(lambda: cur.execute(down, (roots,)).fetchone()[0])
        add(label, "tree: descendants of allowed roots (recursive CTE) -> files", med, best, {**info, "files_found": v})
        up = """with recursive up as (select id, parent_id from library_nodes where id = ANY(%s)
                union select n.id, n.parent_id from library_nodes n join up u on n.id = u.parent_id)
                select count(*) from up"""
        v, med, best = timed(lambda: cur.execute(up, (roots,)).fetchone()[0])
        add(label, "tree: ancestors of allowed roots (breadcrumb set)", med, best, {"nodes": v})

        def python_walk():
            pending, files = list(roots), 0
            while pending:
                rows = cur.execute("select id, kind from library_nodes where organization_id=%s and parent_id = ANY(%s)", (org, pending)).fetchall()
                files += sum(1 for _i, k in rows if k == "file")
                pending = [i for i, k in rows if k == "folder"]
            return files

        v, med, best = timed(python_walk)
        add(label, "tree: same walk level-by-level in Python (as indexed_documents_under)", med, best, {"files_found": v})

        # --- visibility -> document ids (two-step) ---------------------------------------------
        ids_sql = """with recursive sub as (select id from library_nodes where id = ANY(%s)
                     union all select n.id from library_nodes n join sub s on n.parent_id = s.id)
                     select d.id from sub s join library_nodes f on f.id = s.id and f.kind='file'
                     join workspace_folders w on w.source_id = f.source_id
                     join documents d on d.workspace_folder_id = w.id and d.external_file_id = f.external_id and d.index_status='indexed'
                     where d.organization_id = %s"""
        docs, med, best = timed(lambda: [r[0] for r in cur.execute(ids_sql, (roots, org)).fetchall()])
        add(label, "visible indexed document ids (CTE + join documents)", med, best, {"documents": len(docs)})

        # --- search ----------------------------------------------------------------------------
        vis_cte = """with recursive sub as (select id from library_nodes where id = ANY(%(roots)s)
                     union all select n.id from library_nodes n join sub s on n.parent_id = s.id),
                     vis as (select d.id from sub s join library_nodes f on f.id = s.id and f.kind='file'
                             join workspace_folders w on w.source_id = f.source_id
                             join documents d on d.workspace_folder_id = w.id and d.external_file_id = f.external_id and d.index_status='indexed')"""
        one_sql = vis_cte + f""" select c.id from document_chunks c join vis on vis.id = c.document_id
                     where c.organization_id = %(org)s and c.embedding_vec is not null
                     order by c.embedding_vec <=> '{qtext}'::vector limit 100"""
        two_step = f"""select c.id from document_chunks c where c.organization_id = %(org)s and c.document_id = ANY(%(ids)s)
                       and c.embedding_vec is not null order by c.embedding_vec <=> '{qtext}'::vector limit 100"""
        for mode in (["ann", "exact"] if has_hnsw else ["exact"]):
            cur.execute("SET enable_indexscan = %s" % ("on" if mode == "ann" else "off"))
            if mode == "exact":
                cur.execute("SET enable_indexscan = off")
            got, med, best = timed(lambda: [r[0] for r in cur.execute(one_sql, {"roots": roots, "org": org}).fetchall()], runs=2)
            exact_one = got if mode == "exact" else None
            add(label, f"search (a) one SQL CTE+join, {mode}", med, best, {"returned": len(got)})
            if mode == "ann":
                ann_ids = set(got)
            else:
                if has_hnsw:
                    add(label, "   recall@100 of (a) ann vs exact", 0, 0, {"recall": round(len(ann_ids & set(exact_one)) / max(1, len(exact_one)), 3)})
            got2, med2, best2 = timed(lambda: [r[0] for r in cur.execute(two_step, {"org": org, "ids": docs}).fetchall()], runs=2)
            add(label, f"search (b) document_id = ANY({len(docs)} ids), {mode}", med2, best2, {"returned": len(got2)})
        cur.execute("SET enable_indexscan = on")

        # (c) union of whole sync scopes: choose workspaces until ~share of chunks
        ws = [r[0] for r in cur.execute("select id from workspace_folders where organization_id=%s order by name", (org,)).fetchall()]
        k = max(1, round(len(ws) * share))
        fs = ws[:k]
        sql_c = f"""select id from document_chunks where organization_id=%(org)s and workspace_folder_id = ANY(%(f)s)
                    and embedding_vec is not null order by embedding_vec <=> '{qtext}'::vector limit 100"""
        for mode in (["ann", "exact"] if has_hnsw else ["exact"]):
            cur.execute("SET enable_indexscan = %s" % ("on" if mode == "ann" else "off"))
            got, med, best = timed(lambda: [r[0] for r in cur.execute(sql_c, {"org": org, "f": fs}).fetchall()], runs=2)
            add(label, f"search (c) workspace_folder_id = ANY({k} scopes), {mode}", med, best, {"returned": len(got)})
        cur.execute("SET enable_indexscan = on")

        # --- fts under the same visibility ------------------------------------------------------
        stat = cur.execute("select word, ndoc from ts_stat('select search_vector from document_chunks tablesample system (1)') order by ndoc desc").fetchall()
        mid = stat[len(stat) // 40][0]  # moderately common term, not a head word
        fts = f"""select c.id from document_chunks c where c.organization_id=%(org)s and c.document_id = ANY(%(ids)s)
                  and c.search_vector @@ to_tsquery('simple', '{mid}') order by ts_rank_cd(c.search_vector, to_tsquery('simple','{mid}')) desc limit 20"""
        got, med, best = timed(lambda: cur.execute(fts, {"org": org, "ids": docs}).fetchall(), runs=2)
        add(label, f"fts moderately common term '{mid}', document_id = ANY(ids)", med, best, {"returned": len(got)})

    (harness.RESULTS / f"filter_{args.label}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    sys.exit(main())
