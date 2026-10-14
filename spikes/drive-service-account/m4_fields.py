"""Medicao 4: o que o robo (Leitor) enxerga: campos de files.get, sharedWithMe, filhos."""
from lib import Robot, load_state, mask_email, save_result

st = load_state()["folders"]
r = Robot("a")


def presence(obj, prefix=""):
    out = {}
    for k, v in obj.items():
        out[prefix + k] = "<vazio>" if v in (None, "", [], {}) else ("<objeto>" if isinstance(v, dict) else "<valor>")
    return out


def scrub(o):
    if isinstance(o, dict):
        return {k: ("<mascarado>" if k in ("displayName", "photoLink") else scrub(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(i) for i in o]
    return mask_email(o) if isinstance(o, str) else o  # displayName do dono tambem e mascarado abaixo


FIELDS = ("id,name,mimeType,parents,owners(emailAddress,displayName),sharingUser(emailAddress),sharedWithMeTime,"
          "capabilities,copyRequiresWriterPermission,viewersCanCopyContent,writersCanShare,driveId,trashed,ownedByMe,"
          "shared,webViewLink,permissions,permissionIds,modifiedTime,createdTime,md5Checksum,size,version,resourceKey")
out = {"robot": r.email}
g = r.call(f"/files/{st['poc-main']}", {"fields": FIELDS, "supportsAllDrives": "true"})
out["folder_toplevel_get"] = {"status": g["status"], "fields": scrub(g.get("json", {}))}
star = r.call(f"/files/{st['poc-main']}", {"fields": "*", "supportsAllDrives": "true"})
out["folder_toplevel_get_star_presence"] = presence(star.get("json", {})) if star["status"] == 200 else star

# lista tudo que o robo enxerga e separa topo (sharedWithMe) de filhos
allf = []
tok = None
calls = 0
while True:
    params = {"pageSize": 1000, "fields": "nextPageToken,files(id,name,mimeType,parents,sharedWithMeTime)", "supportsAllDrives": "true",
              "includeItemsFromAllDrives": "true", "q": "trashed=false"}
    if tok:
        params["pageToken"] = tok
    res = r.call("/files", params)
    calls += 1
    allf += res["json"]["files"]
    tok = res["json"].get("nextPageToken")
    if not tok:
        break
shared = r.call("/files", {"q": "sharedWithMe=true and trashed=false", "pageSize": 1000, "fields": "files(id,name,mimeType)"})
shared_names = sorted(f["name"] for f in shared["json"]["files"])
out["files_list_all"] = {"calls": calls, "total_visible": len(allf),
                         "folders": sum(1 for f in allf if f["mimeType"].endswith("folder")),
                         "with_sharedWithMeTime": sum(1 for f in allf if f.get("sharedWithMeTime"))}
out["sharedWithMe_list"] = {"names": shared_names, "count": len(shared_names)}
children_in_shared = [f["name"] for f in shared["json"]["files"] if f["name"] in
                      ("raiz-1.txt", "sub", "sub2", "filho-1.txt", "neto-1.txt", "relatorio.pdf", "f001.txt", "d01")]
out["sharedWithMe_contains_children"] = children_in_shared

# um filho e um neto: campos
kids = {f["name"]: f for f in allf if f["name"] in ("raiz-1.txt", "filho-1.txt", "neto-1.txt")}
out["child_get"] = {}
for name, f in kids.items():
    c = r.call(f"/files/{f['id']}", {"fields": "id,name,parents,sharingUser(emailAddress),sharedWithMeTime,capabilities(canDownload,canCopy,canEdit,canShare,canReadRevisions),owners(emailAddress),permissions,size,md5Checksum",
                                     "supportsAllDrives": "true"})
    out["child_get"][name] = {"status": c["status"], "has_sharingUser": bool(c.get("json", {}).get("sharingUser")),
                              "has_sharedWithMeTime": bool(c.get("json", {}).get("sharedWithMeTime")),
                              "has_permissions": bool(c.get("json", {}).get("permissions")),
                              "capabilities": c.get("json", {}).get("capabilities"), "reason": c.get("reason")}
# permissions.list como Leitor
pl = r.call(f"/files/{st['poc-main']}/permissions", {"fields": "permissions(id,type,role)", "supportsAllDrives": "true"})
out["permissions_list_as_reader"] = {"status": pl["status"], "reason": pl.get("reason"), "message": pl.get("message"),
                                     "count": len((pl.get("json") or {}).get("permissions", []))}
# pasta publica (nao compartilhada com o robo)
pub = r.call(f"/files/{st['poc-link-public']}", {"fields": "id,name,mimeType,sharingUser(emailAddress),sharedWithMeTime,capabilities(canDownload),permissionIds", "supportsAllDrives": "true"})
out["public_link_folder_get"] = {"status": pub["status"], "has_sharingUser": bool(pub.get("json", {}).get("sharingUser")),
                                 "has_sharedWithMeTime": bool(pub.get("json", {}).get("sharedWithMeTime")), "name": pub.get("json", {}).get("name"),
                                 "in_sharedWithMe": "poc-link-public" in shared_names}
print(save_result("m04-fields", out))
print({k: out[k] for k in ("files_list_all", "sharedWithMe_list", "sharedWithMe_contains_children", "permissions_list_as_reader", "public_link_folder_get")})
print(out["child_get"])
print({k: v for k, v in out["folder_toplevel_get"]["fields"].items() if k in ("sharingUser", "sharedWithMeTime", "owners", "capabilities", "permissions", "parents", "driveId")})
