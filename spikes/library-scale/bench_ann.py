"""ANN recall/latency under a workspace-folder filter, by hnsw.ef_search (needs ix_spike_hnsw).

    ./run.sh bench_ann.py --label 50k
Ground truth = same statement with enable_indexscan=off (exact scan).  Query vectors: 5 per run, each near a
different topic centroid, so the recall is averaged over several query shapes.
"""
import argparse, json, statistics, sys, time
import numpy as np
import harness


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    meta = harness.load_meta(args.label)
    import psycopg
    conn = psycopg.connect(harness.dsn(harness.db_name(args.label)), autocommit=True)
    cur = conn.cursor()
    org = meta["organization_id"]
    ws = meta["workspace_ids"]
    centroids = np.load(harness.RESULTS / f"centroids_{args.label}.npy")
    rng = np.random.default_rng(5)
    topics = [meta["ws_topics"][i][0] for i in (0, len(ws) // 3, len(ws) // 2, 2 * len(ws) // 3, len(ws) - 1)]
    queries = []
    for t in topics:
        v = 0.5 * centroids[t] + 0.5 * rng.standard_normal(1536).astype("float32") / 39.2
        v = v / np.linalg.norm(v)
        queries.append("[" + ",".join(f"{x:.8f}" for x in v.tolist()) + "]")
    out = {"label": args.label, "rows": []}
    for share_name, n in (("1 scope", 1), ("10%", max(1, round(len(ws) * 0.1))), ("50%", len(ws) // 2), ("100%", len(ws))):
        fl = ws[:n]
        def sql(q):
            return ("select id from document_chunks where organization_id=%s and workspace_folder_id = ANY(%s) "
                    f"and embedding_vec is not null order by embedding_vec <=> '{q}'::vector limit 10")
        cur.execute("set enable_indexscan = off")
        t0 = time.perf_counter()
        exact = [{r[0] for r in cur.execute(sql(q), (org, fl)).fetchall()} for q in queries]
        exact_ms = (time.perf_counter() - t0) * 1000 / len(queries)
        cur.execute("set enable_indexscan = on")
        cur.execute("set hnsw.iterative_scan = relaxed_order")
        cur.execute("set hnsw.max_scan_tuples = 200000")
        for ef in (40, 100, 200, 400):
            cur.execute(f"set hnsw.ef_search = {ef}")
            for q in queries[:1]:  # warm
                cur.execute(sql(q), (org, fl)).fetchall()
            times, rec = [], []
            for q, ex in zip(queries, exact):
                t = time.perf_counter()
                got = {r[0] for r in cur.execute(sql(q), (org, fl)).fetchall()}
                times.append((time.perf_counter() - t) * 1000)
                rec.append(len(got & ex) / max(1, len(ex)))
            row = {"folder_set": share_name, "scopes": n, "ef_search": ef, "median_ms": round(statistics.median(times), 1),
                   "recall_at_10": round(statistics.mean(rec), 3), "exact_ms_per_query": round(exact_ms, 1)}
            out["rows"].append(row)
            print(json.dumps(row), flush=True)
    (harness.RESULTS / f"ann_{args.label}.json").write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    sys.exit(main())
