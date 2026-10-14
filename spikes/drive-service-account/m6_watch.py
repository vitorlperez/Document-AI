"""Medicao 6: feed de mudancas do robo A (changes.list) + plano B (files.list por modifiedTime) + acesso a raiz (files.get).

uso: python m6_watch.py <segundos> [intervalo_s] [nome_do_resultado]
Loga cada evento novo com first_seen_utc e latencia = first_seen - change.time (relogio do Google). Salva results/m06-changes.json.
Tambem registra a transicao do acesso a pasta raiz (poc-main) 200 -> 404 (compartilhamento removido).
"""
import sys
import time
from datetime import datetime, timezone

from lib import Robot, load_state, save_result

total = int(sys.argv[1])
interval = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
OUT = sys.argv[3] if len(sys.argv) > 3 else "m06-changes"
st = load_state()["folders"]
r = Robot("a")
MAIN = st["poc-main"]


def ts(x): return datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
def iso(t): return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds")


start = time.time()
page = r.call("/changes/startPageToken", {"supportsAllDrives": "true"})["json"]["startPageToken"]
since = datetime.fromtimestamp(start - 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
names: dict[str, str] = {}  # id -> ultimo nome conhecido (para eventos 'removed', que nao trazem file)
_tok = None
while True:
    _p = {"q": "trashed=false", "pageSize": 1000, "fields": "nextPageToken,files(id,name)", **({"pageToken": _tok} if _tok else {})}
    _res = r.call("/files", _p)["json"]
    for f in _res["files"]:
        names[f["id"]] = f["name"]
    _tok = _res.get("nextPageToken")
    if not _tok:
        break
parents_of: dict[str, list] = {}
feed, planb, root_access = [], [], []
seen_c, seen_b = set(), set()
last_root = None
polls = 0


def dump():
    save_result(OUT, {"robot": r.email, "started_utc": iso(start), "poll_interval_s": interval, "polls": polls,
                                "plan_b_query_since": since, "changes_feed": feed, "plan_b_modifiedTime_list": planb,
                                "root_access_transitions": root_access})


while time.time() - start < total:
    now = time.time()
    polls += 1
    # (a) acesso a raiz
    g = r.call(f"/files/{MAIN}", {"fields": "id,trashed", "supportsAllDrives": "true"})
    state = (g["status"], g.get("reason"), (g.get("json") or {}).get("trashed"))
    if state != last_root:
        root_access.append({"first_seen_utc": iso(now), "http": g["status"], "reason": g.get("reason"), "trashed": state[2]})
        print("ROOT", root_access[-1], flush=True)
        last_root = state
    # (b) feed
    while True:
        res = r.call("/changes", {"pageToken": page, "pageSize": 1000, "includeRemoved": "true", "supportsAllDrives": "true",
                                  "includeItemsFromAllDrives": "true",
                                  "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,time,changeType,file(id,name,mimeType,parents,trashed,modifiedTime,createdTime,trashedTime))"})
        if res["status"] != 200:
            print("changes status", res["status"], res.get("reason"), flush=True)
            break
        for c in res["json"]["changes"]:
            key = (c["fileId"], c.get("time"), c.get("removed"))
            if key in seen_c:
                continue
            seen_c.add(key)
            f = c.get("file") or {}
            if f.get("name"):
                names[c["fileId"]] = f["name"]
            ev = {"fileId_tail": c["fileId"][-6:], "first_seen_utc": iso(now), "name": f.get("name") or names.get("" + c["fileId"]), "removed": c.get("removed"),
                  "change_time": c.get("time"), "visible_after_s": round(now - ts(c["time"]), 1),
                  "trashed": f.get("trashed"), "has_parents": bool(f.get("parents")), "parents": f.get("parents"),
                  "modifiedTime": f.get("modifiedTime"), "createdTime": f.get("createdTime"), "trashedTime": f.get("trashedTime"),
                  "mime": (f.get("mimeType") or "")[-20:]}
            feed.append(ev)
            print("CHG", {k: ev[k] for k in ("name", "removed", "trashed", "visible_after_s")}, "parents=", ev["has_parents"], flush=True)
        page = res["json"].get("nextPageToken") or res["json"].get("newStartPageToken") or page
        if not res["json"].get("nextPageToken"):
            break
    # (c) plano B
    pb = r.call("/files", {"q": f"modifiedTime > '{since}'", "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                           "fields": "files(id,name,trashed,modifiedTime,parents)"})
    if pb["status"] == 200:
        for f in pb["json"]["files"]:
            key = (f["id"], f["modifiedTime"], f.get("trashed"), tuple(f.get("parents") or []))
            if key in seen_b:
                continue
            seen_b.add(key)
            planb.append({"first_seen_utc": iso(now), "name": f["name"], "trashed": f.get("trashed"), "modifiedTime": f["modifiedTime"],
                          "visible_after_s": round(now - ts(f["modifiedTime"]), 1), "parents": f.get("parents")})
            print("PLANB", planb[-1]["name"], planb[-1]["trashed"], planb[-1]["visible_after_s"], flush=True)
    dump()
    time.sleep(interval)
dump()
print("fim", polls)
