"""Medicao 7: leitura de conteudo (alt=media, export) e pasta/arquivos com download bloqueado."""
import hashlib
import json
from pathlib import Path

from lib import Robot, load_state, save_result

st = load_state()["folders"]
r = Robot("a")
manifest = json.loads((Path(__file__).parent / "fixtures" / "manifest.json").read_text())
EXPORTS = {
    "application/vnd.google-apps.document": ["text/plain", "application/pdf",
                                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "application/vnd.google-apps.spreadsheet": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/pdf"],
    "application/vnd.google-apps.presentation": ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/pdf"],
}
FIELDS = ("id,name,mimeType,size,md5Checksum,parents,capabilities(canDownload,canCopy),copyRequiresWriterPermission,viewersCanCopyContent,"
          "downloadRestrictions,shortcutDetails")


def walk(folder_id, path=""):
    items, tok = [], None
    while True:
        p = {"q": f"'{folder_id}' in parents and trashed=false", "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
             "fields": f"nextPageToken,files({FIELDS})"}
        if tok:
            p["pageToken"] = tok
        res = r.call("/files", p)
        for f in res["json"]["files"]:
            f["path"] = f"{path}/{f['name']}"
            items.append(f)
            if f["mimeType"] == "application/vnd.google-apps.folder":
                items += walk(f["id"], f["path"])
        tok = res["json"].get("nextPageToken")
        if not tok:
            return items


def err(res):
    return {"status": res["status"], "reason": res.get("reason"), "message": (res.get("message") or "")[:160]}


def probe(folder_name, local_prefix):
    rows = []
    for f in walk(st[folder_name]):
        row = {"path": f["path"], "mime": f["mimeType"], "size": f.get("size"),
               "canDownload": f.get("capabilities", {}).get("canDownload"), "canCopy": f.get("capabilities", {}).get("canCopy"),
               "copyRequiresWriterPermission": f.get("copyRequiresWriterPermission"), "downloadRestrictions": f.get("downloadRestrictions")}
        mime = f["mimeType"]
        if mime == "application/vnd.google-apps.folder":
            continue
        if mime == "application/vnd.google-apps.shortcut":
            tgt = f.get("shortcutDetails", {})
            row["shortcut"] = {"targetMimeType": tgt.get("targetMimeType"), "has_targetId": bool(tgt.get("targetId"))}
            if tgt.get("targetId"):
                row["shortcut"]["get_target_as_robot"] = err(r.call(f"/files/{tgt['targetId']}", {"fields": "id,name"}))
            rows.append(row)
            continue
        if mime in EXPORTS:
            row["exports"] = {}
            for em in EXPORTS[mime]:
                res = r.call(f"/files/{f['id']}/export", {"mimeType": em}, raw=True)
                row["exports"][em.split("/")[-1][:40]] = {"status": res["status"], "bytes": res.get("bytes"), **({} if res["status"] == 200 else err(res))}
        else:
            res = r.call(f"/files/{f['id']}", {"alt": "media", "supportsAllDrives": "true"}, raw=True)
            row["alt_media"] = {"status": res["status"], "bytes": res.get("bytes"), **({} if res["status"] == 200 else err(res))}
            if res["status"] == 200:
                key = f"drive-upload/{local_prefix}{f['path']}"
                if key in manifest:
                    row["alt_media"]["sha256_matches_local_fixture"] = hashlib.sha256(res["_content"]).hexdigest() == manifest[key]
        rows.append(row)
    return rows


out = {"robot": r.email}
out["poc-main"] = probe("poc-main", "poc-main")
out["poc-sem-download"] = probe("poc-sem-download", "poc-sem-download")
print(save_result("m07-content", out))
for k in ("poc-main", "poc-sem-download"):
    print("==", k)
    for row in out[k]:
        print(row["path"], row["mime"].split(".")[-1].split("/")[-1][:22], "canDL=", row["canDownload"], "|", {kk: row[kk] for kk in row if kk in ("alt_media", "exports", "shortcut")})
