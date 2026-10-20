"""HTTP-level timings of the endpoints the frontend uses, through the real FastAPI app.

    backend/.venv/bin/python spikes/library-scale/bench_api.py --label 10k [--runs 7]

For each endpoint: median / p95 wall time (in-process TestClient, so it includes routing, auth,
SQL, ORM hydration and JSON serialization but no network), number of SQL statements, time spent in
SQL, and response size. A request that re-runs the same statement shape many times is flagged N+1.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import threading
import time

import harness

PATHS_NOTE = "ms are wall-clock on the dev laptop's docker Postgres (shared_buffers=128MB, untuned)."


class Counter:
    """Process-wide statement log (the TestClient serves requests on another thread, so no thread-local)."""

    def __init__(self, engine):
        from sqlalchemy import event

        self.stmts: list[tuple[str, float]] = []
        self.t0 = 0.0
        self.engine = engine
        event.listen(engine, "before_cursor_execute", self.before)
        event.listen(engine, "after_cursor_execute", self.after)

    def reset(self):
        self.stmts = []

    def before(self, conn, cursor, statement, params, context, many):
        self.t0 = time.perf_counter()

    def after(self, conn, cursor, statement, params, context, many):
        self.stmts.append((statement, (time.perf_counter() - self.t0) * 1000))

    def snapshot(self):
        return list(self.stmts)


def shape(statement: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"%\(\w+\)s|\$\d+|'[^']*'|\b\d+\b", "?", statement))[:160]


def measure(client, counter, name, method, path, *, json_body=None, runs=7, warmup=1):
    def once():
        counter.reset()
        t = time.perf_counter()
        response = client.request(method, path, json=json_body)
        elapsed = (time.perf_counter() - t) * 1000
        return response, elapsed, counter.snapshot()

    for _ in range(warmup):
        once()
    times, last = [], None
    for _ in range(runs):
        response, elapsed, stmts = once()
        times.append(elapsed)
        last = (response, stmts)
    response, stmts = last
    shapes: dict[str, int] = {}
    for s, _ms in stmts:
        shapes[shape(s)] = shapes.get(shape(s), 0) + 1
    worst_shape, worst_count = max(shapes.items(), key=lambda kv: kv[1]) if shapes else ("", 0)
    times.sort()
    row = {
        "name": name, "method": method, "path": path.split("?")[0], "status": response.status_code,
        "median_ms": round(statistics.median(times), 1), "p95_ms": round(times[min(len(times) - 1, int(len(times) * 0.95))], 1),
        "min_ms": round(times[0], 1), "statements": len(stmts), "sql_ms": round(sum(ms for _s, ms in stmts), 1),
        "bytes": len(response.content), "repeated_shape_max": worst_count,
        "repeated_shape": worst_shape if worst_count >= 10 else "",
    }
    if response.status_code >= 400:
        row["error"] = response.text[:200]
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--skip-ask", action="store_true")
    args = parser.parse_args()
    meta = harness.load_meta(args.label)
    client, factory, engine = harness.make_client(harness.db_name(args.label))
    harness.login(client)
    org = harness.first_org(client)
    assert str(org) == meta["organization_id"], "login resolved a different organization"
    counter = Counter(engine)
    q = f"organization_id={org}"
    root = meta["source_root_node_id"]
    ws_big = meta["workspace_ids"][0]  # holds the flat Inbox folder
    ws_mid = meta["workspace_ids"][len(meta["workspace_ids"]) // 2]
    rows = []
    runs = args.runs

    def add(*a, **k):
        r = measure(client, counter, *a, runs=k.pop("runs", runs), **k)
        rows.append(r)
        print(f"{r['name']:<46} {r['median_ms']:>9.1f} ms  p95 {r['p95_ms']:>9.1f}  sql {r['statements']:>4} stmts {r['sql_ms']:>8.1f} ms  {r['bytes']/1024:>9.1f} KiB  [{r['status']}]"
              + (f"  N+1:{r['repeated_shape_max']}x" if r['repeated_shape'] else ""), flush=True)
        return r

    # Library tree ----------------------------------------------------------------------------
    add("GET /library (roots)", "GET", f"/library?{q}")
    add("GET children(source root) page1/100", "GET", f"/library/nodes/{root}/children?{q}&page=1&page_size=100")
    add("GET children(source root) last page", "GET", f"/library/nodes/{root}/children?{q}&page=999&page_size=100")
    # workspace root of ws 0 -> its children (includes the Inbox)
    top0 = meta["workspace_root_nodes"][0]
    add("GET children(workspace root 0)", "GET", f"/library/nodes/{top0}/children?{q}&page=1&page_size=100")
    # Inbox: the big flat folder (if any) found through the children listing
    resp = client.get(f"/library/nodes/{top0}/children?{q}&page=1&page_size=100")
    inbox = next((i["id"] for i in resp.json()["items"] if i["name"].startswith("Inbox")), None)
    if inbox:
        add(f"GET children(Inbox ~{meta['inbox_files']} files) p1/100", "GET", f"/library/nodes/{inbox}/children?{q}&page=1&page_size=100")
        pages = max(1, meta["inbox_files"] // 100)
        add(f"GET children(Inbox) p{pages}/100 (deep offset)", "GET", f"/library/nodes/{inbox}/children?{q}&page={pages}&page_size=100")
    add("GET /library/search 'ra' (very common)", "GET", f"/library/search?{q}&query=ra&page=1&page_size=50")
    add("GET /library/search '0000042' (rare)", "GET", f"/library/search?{q}&query=0000042&page=1&page_size=50")
    add("GET /library/question-contexts", "GET", f"/library/question-contexts?{q}")
    add("GET /library/mention-candidates q='' ", "GET", f"/library/mention-candidates?{q}&q=&limit=20")
    add("GET /library/mention-candidates q='doc'", "GET", f"/library/mention-candidates?{q}&q=ra&limit=20")
    add("GET /library/sync-status", "GET", f"/library/sync-status?{q}")
    add("GET /library/syncs", "GET", f"/library/syncs?{q}")
    add("GET /library/sync-history", "GET", f"/library/sync-history?{q}")
    add("GET /workspace-folders", "GET", f"/workspace-folders?{q}")
    add("GET /workspace-folders/{big}/documents (unpaged)", "GET", f"/workspace-folders/{ws_big}/documents?{q}")
    add("GET /workspace-folders/{mid}/documents (unpaged)", "GET", f"/workspace-folders/{ws_mid}/documents?{q}")
    add("GET /organizations/{id}/usage", "GET", f"/organizations/{org}/usage")
    from sqlalchemy import text as _text

    with engine.connect() as _c:  # real vocabulary of this dataset (the synthetic words are not English)
        stat = _c.execute(_text("select word, ndoc from ts_stat('select search_vector from document_chunks tablesample system (1)') order by ndoc desc")).all()
    common_q = " ".join(w for w, _n in stat[5:7])
    rare_q = next(w for w, n in reversed(stat) if n >= 3)
    add("POST /workspace-folders/{big}/search (rare term)", "POST", f"/workspace-folders/{ws_big}/search?{q}",
        json_body={"query": rare_q, "page": 1, "page_size": 20})
    add("POST /workspace-folders/{big}/search (2 common terms)", "POST", f"/workspace-folders/{ws_big}/search?{q}",
        json_body={"query": common_q, "page": 1, "page_size": 20})
    add("POST /workspace-folders/{big}/search (2 common, page 5)", "POST", f"/workspace-folders/{ws_big}/search?{q}",
        json_body={"query": common_q, "page": 5, "page_size": 20})

    # Questions: stub provider, no network. Reset the monthly counters first. ------------------
    if not args.skip_ask:
        import numpy as np

        centroids = np.load(harness.RESULTS / f"centroids_{args.label}.npy")
        topic = meta["ws_topics"][0][0]
        qv = (0.5 * centroids[topic] + 0.5 * np.random.default_rng(1).standard_normal(1536).astype("float32") / 39.2)
        provider = harness.RandomEmbedProvider([float(x) for x in qv / np.linalg.norm(qv)])
        client.app.state.semantic_provider = provider
        from sqlalchemy import text

        def reset_usage():
            with engine.begin() as conn:
                conn.execute(text("delete from usage_records"))

        reset_usage()
        add("POST single-folder question (1 workspace)", "POST", f"/workspace-folders/{ws_mid}/questions?{q}",
            json_body={"question": "ratomi doluke", "scope": "folder"}, runs=3, warmup=1)
        reset_usage()
        add("POST org-scope question (ALL workspaces)", "POST", f"/organizations/{org}/questions",
            json_body={"question": "ratomi doluke", "scope": "organization"}, runs=3, warmup=1)
        reset_usage()

    out = {"label": args.label, "meta": {k: meta[k] for k in ("files", "nodes", "documents_rows", "active_documents", "chunks", "workspaces")},
           "note": PATHS_NOTE, "rows": rows}
    (harness.RESULTS / f"api_{args.label}{'_noask' if args.skip_ask else ''}.json").write_text(json.dumps(out, indent=1))
    client.__exit__(None, None, None)


if __name__ == "__main__":
    sys.exit(main())
