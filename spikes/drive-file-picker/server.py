#!/usr/bin/env python3
"""PoC ADR-0017 B7.0: drive.file + Google Picker. Local only (http://localhost:8765).

Credentials (never printed/logged):
  GOOGLE_OAUTH_CLIENT_ID  <- ../../.env (root) or env
  GOOGLE_PICKER_API_KEY   <- spikes/drive-file-picker/.env.local or env
Access tokens live only in this process memory.
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PORT = 8765
API = "https://www.googleapis.com/drive/v3"
FOLDER = "application/vnd.google-apps.folder"


def load_env():
    env = {}
    for p in (ROOT / ".env", HERE / ".env.local"):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("GOOGLE_")})
    return env


ENV = load_env()
STATE = {"token": None, "picks": {}, "baseline": {}}  # picks: label -> list[{id,name,mimeType}]


def call(path, params=None, raw=False):
    """Return (http_status, parsed_json_or_bytes_len, error_reason)."""
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {STATE['token']}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return r.status, (len(body) if raw else json.loads(body)), None
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read())["error"]["errors"][0]["reason"]
        except Exception:
            reason = "?"
        return e.code, None, reason


def list_children(folder_id, log):
    items, page = [], None
    while True:
        p = {"q": f"'{folder_id}' in parents and trashed = false",
             "fields": "nextPageToken,files(id,name,mimeType,parents,size)", "pageSize": 1000,
             "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
        if page:
            p["pageToken"] = page
        st, js, err = call("files", p)
        log.append({"call": "files.list q='<folder>' in parents", "http": st, "reason": err,
                    "count": len(js["files"]) if js else None})
        if st != 200:
            return items, st
        items += js["files"]
        page = js.get("nextPageToken")
        if not page:
            return items, 200


def crawl(folder_id, log):
    """BFS; returns list of (depth, item)."""
    out, queue = [], [(folder_id, 0)]
    while queue:
        fid, d = queue.pop(0)
        kids, st = list_children(fid, log)
        for k in kids:
            out.append((d + 1, k))
            if k["mimeType"] == FOLDER:
                queue.append((k["id"], d + 1))
    return out


def try_read(item):
    mt = item["mimeType"]
    if mt == FOLDER:
        return None
    if mt.startswith("application/vnd.google-apps."):
        exp = "text/csv" if mt.endswith("spreadsheet") else "text/plain"
        st, n, err = call(f"files/{item['id']}/export", {"mimeType": exp}, raw=True)
        return {"op": f"files.export {exp}", "http": st, "bytes": n, "reason": err}
    st, n, err = call(f"files/{item['id']}", {"alt": "media"}, raw=True)
    return {"op": "files.get alt=media", "http": st, "bytes": n, "reason": err}


def verify(phase):
    result = {"phase": phase, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "picks": {}}
    for label, picks in STATE["picks"].items():
        res = []
        for pk in picks:
            log = []
            st, meta, err = call(f"files/{pk['id']}", {"fields": "id,name,mimeType,parents,capabilities/canListChildren",
                                                         "supportsAllDrives": "true"})
            entry = {"picked": {"name": pk["name"], "mimeType": pk["mimeType"]},
                     "files.get": {"http": st, "reason": err}}
            if st == 200 and meta["mimeType"] == FOLDER:
                tree = crawl(pk["id"], log)
                entry["files.list_calls"] = log
                entry["descendants_total"] = len(tree)
                entry["by_depth"] = {str(d): sum(1 for x, _ in tree if x == d) for d in sorted({x for x, _ in tree})}
                entry["descendants"] = [{"depth": d, "name": i["name"], "mimeType": i["mimeType"], "id": i["id"]} for d, i in tree]
                reads = []
                for d, i in tree:
                    r = try_read(i)
                    if r:
                        reads.append({"name": i["name"], "depth": d, **r})
                entry["reads"] = reads
                entry["reads_ok"] = sum(1 for r in reads if r["http"] == 200)
                entry["reads_fail"] = sum(1 for r in reads if r["http"] != 200)
            elif st == 200:
                entry["read"] = try_read(meta)
            res.append(entry)
        result["picks"][label] = res
    # whole-visibility (what drive.file exposes to the app at all)
    allv, page, calls = [], None, 0
    while True:
        p = {"q": "trashed = false", "fields": "nextPageToken,files(id,name,mimeType,parents)", "pageSize": 1000}
        if page:
            p["pageToken"] = page
        st, js, err = call("files", p)
        calls += 1
        if st != 200:
            result["files.list_all"] = {"http": st, "reason": err}
            break
        allv += js["files"]
        page = js.get("nextPageToken")
        if not page:
            result["files.list_all"] = {"http": 200, "calls": calls, "visible_total": len(allv),
                                        "names": sorted(f["name"] for f in allv)}
            break
    if phase == "baseline":
        st, js, err = call("changes/startPageToken", {"supportsAllDrives": "true"})
        result["changes.startPageToken"] = {"http": st, "reason": err}
        STATE["baseline"] = {"startPageToken": js["startPageToken"] if js else None,
                             "names": {f["name"] for f in allv},
                             "desc": {l: {e_i["id"] for e in r for e_i in e.get("descendants", [])} for l, r in result["picks"].items()}}
    else:
        base = STATE["baseline"]
        tok = base.get("startPageToken")
        if tok:
            chg, page, calls = [], tok, 0
            while page:
                st, js, err = call("changes", {"pageToken": page, "pageSize": 1000, "includeRemoved": "true",
                                               "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                                               "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,file(name,mimeType,parents,trashed))"})
                calls += 1
                if st != 200:
                    result["changes.list"] = {"http": st, "reason": err}
                    break
                chg += js.get("changes", [])
                page = js.get("nextPageToken")
            else:
                result["changes.list"] = {"http": 200, "calls": calls, "total_changes": len(chg),
                                          "changes": [{"name": (c.get("file") or {}).get("name"), "removed": c.get("removed"),
                                                       "mimeType": (c.get("file") or {}).get("mimeType")} for c in chg]}
        new_in_list = {}
        for label, r in result["picks"].items():
            old = base["desc"].get(label, set())
            new_in_list[label] = [d["name"] + f" (depth {d['depth']})" for e in r for d in e.get("descendants", []) if d["id"] not in old]
        result["new_via_files_list_vs_baseline"] = new_in_list
        result["new_visible_names_vs_baseline"] = sorted(set(n for n in result.get("files.list_all", {}).get("names", [])) - base.get("names", set()))
    out = HERE / "results" / f"{phase}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def control():
    """Controle positivo: o PRÓPRIO app cria um arquivo na pasta escolhida (drive.file permite) e tenta listar/ler de volta."""
    out = {"phase": "control", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    pk = next((p for l in ("folder-mode", "folders-view") for p in STATE["picks"].get(l, []) if p["mimeType"] == FOLDER), None)
    if not pk:
        return {"error": "no folder picked"}
    boundary = "xBOUNDARYx"
    meta = json.dumps({"name": "criado-pelo-app.txt", "parents": [pk["id"]], "mimeType": "text/plain"})
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n--{boundary}\r\n"
            f"Content-Type: text/plain\r\n\r\nconteudo criado pelo app\r\n--{boundary}--").encode()
    req = urllib.request.Request("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,parents",
                                 data=body, headers={"Authorization": f"Bearer {STATE['token']}",
                                                     "Content-Type": f"multipart/related; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out["files.create_in_picked_folder"] = {"http": r.status}
            new_id = json.loads(r.read())["id"]
    except urllib.error.HTTPError as e:
        out["files.create_in_picked_folder"] = {"http": e.code}
        return out
    log = []
    kids, st = list_children(pk["id"], log)
    out["files.list_after_create"] = {"http": st, "children": [k["name"] for k in kids]}
    out["read_back"] = try_read({"id": new_id, "mimeType": "text/plain", "name": "x"})
    (HERE / "results" / "control.json").write_text(json.dumps(out, indent=2))
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence (URLs may carry nothing sensitive, but keep quiet)
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if path.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path.path == "/config":
            cid = ENV.get("GOOGLE_OAUTH_CLIENT_ID", "")
            return self.send(200, {"clientId": cid, "apiKey": ENV.get("GOOGLE_PICKER_API_KEY", ""),
                                   "appId": cid.split("-")[0]})
        if path.path == "/control" and STATE["token"]:
            return self.send(200, control())
        if path.path == "/verify":
            phase = urllib.parse.parse_qs(path.query).get("phase", ["baseline"])[0]
            if not STATE["token"] or not STATE["picks"]:
                return self.send(400, {"error": "no token/picks yet"})
            try:
                return self.send(200, verify(phase))
            except Exception as e:  # noqa
                return self.send(500, {"error": repr(e)})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/token":
            STATE["token"] = body["token"]
            return self.send(200, {"ok": True})
        if self.path == "/picks":
            STATE["picks"][body["label"]] = body["docs"]
            return self.send(200, {"ok": True, "labels": list(STATE["picks"])})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"clientId set: {bool(ENV.get('GOOGLE_OAUTH_CLIENT_ID'))} | apiKey set: {bool(ENV.get('GOOGLE_PICKER_API_KEY'))}")
    print(f"open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
