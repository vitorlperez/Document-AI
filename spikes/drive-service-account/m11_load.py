"""Medicao 11: custo de sync de arvore sintetica (1000 arquivos / 50 pastas) + simulacao de 20 orgs x ciclo de 15 min.

Tudo com UM robo (A): pior caso (na arquitetura (b) cada org tem seu proprio balde 'por usuario').
"""
import collections
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from lib import Robot, load_state, save_result

st = load_state()["folders"]
root = st["arvore-1000"]
r = Robot("a")
r.token()
stats = collections.Counter()
lock = threading.Lock()
orig_call = r.call


def counted(*a, **kw):
    kw.setdefault("retries", 0)  # retries so nos nossos loops, para contar 403/429 de verdade
    res = orig_call(*a, **kw)
    with lock:
        stats["calls"] += 1
        stats[f"http_{res['status']}"] += 1
        if res["status"] >= 400:
            stats[f"reason_{res.get('reason')}"] += 1
    return res


r.call = counted  # type: ignore[method-assign]
Q = {"pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
     "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size,parents)"}


def list_children(fid):
    out, tok = [], None
    while True:
        res = r.call("/files", {**Q, "q": f"'{fid}' in parents and trashed=false", **({"pageToken": tok} if tok else {})})
        if res["status"] != 200:
            return None
        out += res["json"]["files"]
        tok = res["json"].get("nextPageToken")
        if not tok:
            return out


def bfs():
    files, folders, queue = [], 0, [root]
    while queue:
        kids = list_children(queue.pop())
        if kids is None:
            continue
        for k in kids:
            if k["mimeType"].endswith("folder"):
                folders += 1
                queue.append(k["id"])
            else:
                files.append(k)
    return files, folders


def snapshot(label, fn):
    before = dict(stats)
    t0 = time.perf_counter()
    res = fn()
    dt = time.perf_counter() - t0
    delta = {k: stats[k] - before.get(k, 0) for k in stats if stats[k] != before.get(k, 0)}
    return {"label": label, "seconds": round(dt, 2), "api": delta}, res


out = {"robot": r.email}
# 1) descoberta por BFS (como o conector atual faz)
snap, (files, nfolders) = snapshot("bfs_listagem_por_pasta", bfs)
snap.update(files=len(files), folders=nfolders)
out["bfs"] = snap
# 2) listagem global paginada (alternativa barata): 1 chamada por 1000 itens
def global_list():
    n, tok = 0, None
    while True:
        res = r.call("/files", {**Q, "q": "trashed=false", **({"pageToken": tok} if tok else {})})
        n += len(res["json"]["files"])
        tok = res["json"].get("nextPageToken")
        if not tok:
            return n
snap, n_visible = snapshot("listagem_global_paginada", global_list)
snap["items_visible_total"] = n_visible
out["global_list"] = snap
# 3) feed incremental sem mudancas
def changes_idle():
    sp = r.call("/changes/startPageToken", {"supportsAllDrives": "true"})["json"]["startPageToken"]
    return r.call("/changes", {"pageToken": sp, "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "fields": "changes(fileId),newStartPageToken"})
out["changes_idle"], _ = snapshot("changes_sem_mudancas", changes_idle)
# 4) download de todos os 1000 arquivos com 3 workers (MAX_EXTRACTION_WORKERS=3 do produto)
def download_all():
    def one(f):
        return r.call(f"/files/{f['id']}", {"alt": "media", "supportsAllDrives": "true"}, raw=True)["status"]
    with ThreadPoolExecutor(3) as ex:
        return collections.Counter(ex.map(one, files))
snap, codes = snapshot("download_1000_arquivos_3_workers", download_all)
snap["http_codes"] = dict(codes)
snap["files_per_second"] = round(len(files) / snap["seconds"], 1)
out["download_all"] = snap
# 5) simulacao: 20 orgs, cada uma faz 1 ciclo de descoberta BFS (~51 chamadas); o mais rapido possivel com 4 workers
def sim20():
    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(lambda _: len(bfs()[0]), range(20)))
snap, sizes = snapshot("simulacao_20_orgs_discovery_burst_4_workers", sim20)
snap["each_run_files"] = sorted(set(sizes))
snap["calls_per_second"] = round(snap["api"].get("calls", 0) / snap["seconds"], 1)
out["sim_20_orgs"] = snap
# 6) cotas reais do projeto (Service Usage API, token do gcloud do dono)
try:
    tok = subprocess.run(["/opt/homebrew/bin/gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=60).stdout.strip()
    j = httpx.get("https://serviceusage.googleapis.com/v1beta1/projects/arquivio-drive-poc/services/drive.googleapis.com/consumerQuotaMetrics?view=BASIC",
                  headers={"Authorization": f"Bearer {tok}", "x-goog-user-project": "arquivio-drive-poc"}, timeout=60).json()
    out["drive_quotas"] = [{"metric": m.get("displayName"), "unit": l.get("unit"), "limit": b.get("effectiveLimit")}
                           for m in j.get("metrics", []) for l in m.get("consumerQuotaLimits", []) for b in l.get("quotaBuckets", [])]
except Exception as e:  # noqa: BLE001
    out["drive_quotas"] = f"indisponivel: {type(e).__name__}"
# conta de margem
calls_one_org_cycle = out["bfs"]["api"].get("calls", 0)
out["margin_estimate"] = {
    "calls_per_org_discovery_cycle": calls_one_org_cycle,
    "orgs": 20, "cycle_minutes": 15,
    "steady_calls_per_minute_all_orgs_discovery_only": round(calls_one_org_cycle * 20 / 15, 1),
}
print(save_result("m11-load", out))
import json
print(json.dumps({k: out[k] for k in out if k not in ("drive_quotas",)}, indent=1))
print(json.dumps(out["drive_quotas"], indent=0)[:2500])
