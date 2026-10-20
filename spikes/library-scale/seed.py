"""Synthetic corpus generator for the library-scale spike.

    PYTHONPATH=<numpy site> backend/.venv/bin/python spikes/library-scale/seed.py \
        --label 10k --files 10000 --workspaces 40 --chunks-per-doc 5

Creates database spike_ls_<label> from the migrated template, creates the organization through the
real API (so memberships/settings are the real ones), then bulk-loads with COPY:

  * library_nodes  : one `source` root, W workspace roots (depth 1), random sub-folders down to depth 5,
                     --files `file` leaves (Pareto-skewed folder sizes + one big flat "Inbox" folder)
  * workspace_folders (+selection, + 20 processing_jobs each) : one per workspace root ("Espaço")
  * documents      : one `indexed` row per file (1% failed, 2% removed) + 5% extra copies in a second
                     workspace (the overlap case: same Drive file synced by two scopes)
  * document_chunks: Poisson(chunks-per-doc) chunks per indexed doc, 1536-d clustered embeddings in
                     BOTH `embedding` (json) and `embedding_vec` (vector), like the app's dual write.

Scale label = number of file nodes. Active documents (index_status='indexed') end up ~1.04x that.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import psycopg

import harness

DIMS = 1536
TOPICS = 200
SYLLABLES = ["ra", "to", "mi", "ke", "lu", "sa", "ne", "do", "vi", "po", "an", "el", "or", "cu", "ba", "ti"]
EMBEDDING_MODEL = "text-embedding-3-small"  # app.knowledge.questions.EMBEDDING_MODEL


def uid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def fmt_vec(row) -> str:
    return "[" + ",".join(map("{:.8f}".format, row.tolist())) + "]"


def make_vocab(rng: random.Random, size: int = 6000) -> list[str]:
    words = set()
    while len(words) < size:
        words.add("".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 4))))
    return sorted(words)


def make_text_pool(rng: random.Random, vocab: list[str], chars: int, n: int = 4000) -> list[str]:
    # Zipf-ish word frequency so a few terms are very common (like real prose) and most are rare.
    weights = [1.0 / (rank + 1) ** 0.9 for rank in range(len(vocab))]
    cum = list(__import__("itertools").accumulate(weights))
    pool = []
    for _ in range(n):
        target = max(80, int(rng.gauss(chars, chars * 0.35)))
        parts, size = [], 0
        while size < target:
            word = rng.choices(vocab, cum_weights=cum)[0]
            parts.append(word)
            size += len(word) + 1
        pool.append(" ".join(parts))
    return pool


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--files", type=int, required=True)
    parser.add_argument("--workspaces", type=int, required=True)
    parser.add_argument("--chunks-per-doc", type=float, default=5.0)
    parser.add_argument("--chunk-chars", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    started = time.perf_counter()
    database = harness.db_name(args.label)
    harness.create_db_from_template(database)
    rng = random.Random(args.seed)
    nprng = np.random.default_rng(args.seed)

    # --- organization / user through the real API -------------------------------------------------
    client, factory, engine = harness.make_client(database)
    harness.login(client)
    org_id = harness.create_org(client, f"Spike {args.label}")
    client.__exit__(None, None, None)
    engine.dispose()
    print(f"[{time.perf_counter()-started:6.1f}s] org {org_id}")

    conn = psycopg.connect(harness.dsn(database))
    conn.autocommit = False
    cur = conn.cursor()
    owner_id = cur.execute("select user_id from memberships where organization_id=%s", (org_id,)).fetchone()[0]
    source_id = uid(rng)
    cur.execute(
        "insert into data_sources (id, organization_id, provider, encrypted_credentials, status, connected_by_user_id) "
        "values (%s,%s,'google_drive','x','connected',%s)", (source_id, org_id, owner_id))
    root_id = uid(rng)
    now = datetime.now(UTC)

    # --- tree --------------------------------------------------------------------------------------
    W = args.workspaces
    n_files = args.files
    folders_total = max(W, n_files // 25)  # ~25 files per folder on average
    per_ws_folders = max(1, folders_total // W)
    per_ws_files = [n_files // W + (1 if i < n_files % W else 0) for i in range(W)]
    vocab = make_vocab(rng)
    pool = make_text_pool(rng, vocab, args.chunk_chars)

    nodes = []  # (id, parent, external_id, kind, name, mime, url)
    nodes.append((root_id, None, "__company_library_source_root__", "source", "Google Drive", None, None))
    ws_rows = []  # (ws_id, name, external_folder_id, root_folder_node)
    files = []  # (node_id, ws_idx, external_id, name, mime, url, status)
    ws_topics = [nprng.choice(TOPICS, size=8, replace=False) for _ in range(W)]
    mimes = ["application/pdf"] * 6 + ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"] * 2 + ["text/plain"] * 2
    inbox_n = min(n_files // 10, 5000)

    for w in range(W):
        ws_id = uid(rng)
        top_id = uid(rng)
        top_ext = f"drv-ws{w}"
        nodes.append((top_id, root_id, top_ext, "folder", f"Espaço {w:03d} {rng.choice(vocab)}", None, None))
        ws_rows.append((ws_id, f"Espaço {w:03d}", top_ext, top_id))
        folders = [(top_id, 1)]  # (node_id, depth)
        for j in range(per_ws_folders - 1):
            candidates = [f for f in folders if f[1] < 5]
            parent = rng.choice(candidates)
            fid = uid(rng)
            nodes.append((fid, parent[0], f"drv-ws{w}-f{j}", "folder", f"Pasta {w}-{j} {rng.choice(vocab)}", None, None))
            folders.append((fid, parent[1] + 1))
        inbox_id = None
        if w == 0 and inbox_n:
            inbox_id = uid(rng)
            nodes.append((inbox_id, top_id, "drv-inbox", "folder", "Inbox (pasta plana gigante)", None, None))
        weights = nprng.pareto(1.5, size=len(folders)) + 1.0
        weights = weights / weights.sum()
        picks = nprng.choice(len(folders), size=per_ws_files[w], p=weights)
        for k in range(per_ws_files[w]):
            fi = k + sum(per_ws_files[:w])
            parent = folders[picks[k]][0]
            if inbox_id is not None and k < inbox_n:
                parent = inbox_id
            roll = rng.random()
            status = "failed" if roll < 0.01 else "removed" if roll < 0.03 else "indexed"
            ext = f"drv-f{fi:07d}"
            mime = rng.choice(mimes)
            suffix = {"application/pdf": ".pdf", "text/plain": ".txt"}.get(mime, ".docx")
            name = f"{rng.choice(vocab)} {rng.choice(vocab)} {fi:07d}{suffix}"
            node_id = uid(rng)
            nodes.append((node_id, parent, ext, "file", name, mime, f"https://drive.example.test/file/{ext}"))
            files.append((node_id, w, ext, name, mime, f"https://drive.example.test/file/{ext}", status))
    print(f"[{time.perf_counter()-started:6.1f}s] tree built: {len(nodes)} nodes ({sum(1 for n in nodes if n[3]=='folder')} folders)")

    with cur.copy("COPY library_nodes (id, organization_id, source_id, parent_id, external_id, kind, name, mime_type, source_url) FROM STDIN") as cp:
        # parents are always created before children above, but FK is checked at statement end anyway
        for n in nodes:
            cp.write_row((n[0], org_id, source_id, n[1], n[2], n[3], n[4], n[5], n[6]))
    with cur.copy("COPY workspace_folders (id, organization_id, source_id, external_folder_id, name, uniform_access_confirmed, status, last_synced_at) FROM STDIN") as cp:
        for ws_id, name, ext, _top in ws_rows:
            cp.write_row((ws_id, org_id, source_id, ext, name, True, "ready", now))
    with cur.copy("COPY workspace_folder_selections (id, workspace_folder_id, kind, external_folder_id) FROM STDIN") as cp:
        for ws_id, _name, ext, _top in ws_rows:
            cp.write_row((uid(rng), ws_id, "folder", ext))
    with cur.copy("COPY processing_jobs (id, organization_id, workspace_folder_id, status, idempotency_key, started_at, completed_at) FROM STDIN") as cp:
        for ws_id, _name, _ext, _top in ws_rows:
            for h in range(20):
                t = now - timedelta(days=h, minutes=rng.randint(0, 600))
                cp.write_row((uid(rng), org_id, ws_id, "ready", f"seed-{ws_id}-{h}", t, t + timedelta(minutes=3)))
    conn.commit()
    print(f"[{time.perf_counter()-started:6.1f}s] nodes/workspaces/jobs loaded")

    # --- documents (+ overlap copies) -------------------------------------------------------------
    docs = []  # (doc_id, ws_idx, ext, name, mime, url, status, topic)
    for node_id, w, ext, name, mime, url, status in files:
        docs.append((uid(rng), w, ext, name, mime, url, status, int(nprng.choice(ws_topics[w]))))
        if status == "indexed" and rng.random() < 0.05 and W > 1:
            other = (w + 1 + rng.randrange(W - 1)) % W
            docs.append((uid(rng), other, ext, name, mime, url, "indexed", int(nprng.choice(ws_topics[other]))))
    ws_ids = [r[0] for r in ws_rows]
    with cur.copy("COPY documents (id, organization_id, workspace_folder_id, external_file_id, name, mime_type, source_url, content_hash, modified_at, indexed_at, processing_version, index_status, error_code) FROM STDIN") as cp:
        for doc_id, w, ext, name, mime, url, status, _t in docs:
            cp.write_row((doc_id, org_id, ws_ids[w], ext, name, mime, url, "a" * 64,
                          now - timedelta(days=rng.randint(0, 700)), now if status == "indexed" else None,
                          "v1", status, "extract_failed" if status == "failed" else None))
    conn.commit()
    indexed_docs = [d for d in docs if d[6] == "indexed"]
    print(f"[{time.perf_counter()-started:6.1f}s] documents loaded: {len(docs)} rows, {len(indexed_docs)} indexed")

    # --- chunks + embeddings ----------------------------------------------------------------------
    centroids = nprng.standard_normal((TOPICS, DIMS), dtype=np.float32)
    centroids /= np.linalg.norm(centroids, axis=1, keepdims=True)
    A = 0.5  # topic weight: same-topic cosine ~0.5, cross-topic ~0 (text-embedding-3-small-like spread)
    chunk_total = 0
    batch_docs, batch_n = [], 0

    def flush(cp, batch):
        nonlocal chunk_total
        total = sum(n for _d, n in batch)
        noise = nprng.standard_normal((total, DIMS), dtype=np.float32)
        noise /= np.linalg.norm(noise, axis=1, keepdims=True)
        cursor_i = 0
        for (doc, n_chunks) in batch:
            doc_id, w, ext, name, _mime, _url, _status, topic = doc
            for pos in range(n_chunks):
                v = A * centroids[topic] + (1 - A) * noise[cursor_i]
                v /= np.linalg.norm(v)
                cursor_i += 1
                text = pool[rng.randrange(len(pool))]
                vec = fmt_vec(v)
                cp.write_row((uid(rng), org_id, ws_ids[w], doc_id, pos, text, f"{name}\n{text}",
                              vec, vec, EMBEDDING_MODEL, 1 + pos // 3))
        chunk_total += total

    with cur.copy("COPY document_chunks (id, organization_id, workspace_folder_id, document_id, position, text, search_text, embedding, embedding_vec, embedding_model, page_number) FROM STDIN") as cp:
        for doc in indexed_docs:
            n_chunks = max(1, int(nprng.poisson(args.chunks_per_doc)))
            batch_docs.append((doc, n_chunks))
            batch_n += n_chunks
            if batch_n >= 3000:
                flush(cp, batch_docs)
                batch_docs, batch_n = [], 0
                if chunk_total % 30000 < 3000:
                    print(f"[{time.perf_counter()-started:6.1f}s] chunks {chunk_total}", flush=True)
        if batch_docs:
            flush(cp, batch_docs)
    conn.commit()
    print(f"[{time.perf_counter()-started:6.1f}s] chunks loaded: {chunk_total}")

    conn.autocommit = True
    cur = conn.cursor()
    # docker's default /dev/shm is 64MB: a parallel VACUUM needs more -> "DiskFull ... shared memory segment"
    cur.execute("SET max_parallel_maintenance_workers = 0")
    cur.execute("VACUUM (ANALYZE)")
    sizes = dict(cur.execute(
        "select relname, pg_total_relation_size(oid) from pg_class where relname in ('document_chunks','documents','library_nodes')").fetchall())
    meta = {
        "label": args.label, "database": database, "organization_id": str(org_id), "owner_user_id": str(owner_id),
        "source_id": str(source_id), "source_root_node_id": str(root_id),
        "workspace_ids": [str(x) for x in ws_ids], "workspace_root_nodes": [str(r[3]) for r in ws_rows],
        "files": n_files, "nodes": len(nodes), "documents_rows": len(docs), "active_documents": len(indexed_docs),
        "chunks": chunk_total, "workspaces": W, "chunks_per_doc": args.chunks_per_doc, "chunk_chars": args.chunk_chars,
        "inbox_files": inbox_n, "table_bytes": sizes, "seed_seconds": round(time.perf_counter() - started, 1),
        "topics": TOPICS, "ws_topics": [[int(t) for t in ts] for ts in ws_topics],
    }
    (harness.RESULTS / f"meta_{args.label}.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k not in {"workspace_ids", "workspace_root_nodes", "ws_topics"}}, indent=1))
    # centroids are needed by bench scripts to build realistic query vectors
    np.save(harness.RESULTS / f"centroids_{args.label}.npy", centroids)
    conn.close()


if __name__ == "__main__":
    main()
