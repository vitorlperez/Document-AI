"""Medicao 5: isolamento. Robo B (sem compartilhamento) tenta ler pastas que so o robo A enxerga, e a pasta 'qualquer pessoa com o link'."""
import json
import secrets
import string

from lib import Robot, load_state, save_result

st = load_state()["folders"]
a, b = Robot("a"), Robot("b")
ALPHA = string.ascii_letters + string.digits + "-_"
fake = "".join(secrets.choice(ALPHA) for _ in range(len(st["poc-main"])))  # mesmo tamanho de um ID real, inexistente
F = {"fields": "id,name,mimeType", "supportsAllDrives": "true"}


def norm(res, real_id=None):
    """Resposta normalizada para comparar corpos de erro (troca o ID por <ID>)."""
    msg = res.get("message") or ""
    for x in (real_id, fake):
        if x:
            msg = msg.replace(x, "<ID>")
    return {"status": res["status"], "reason": res.get("reason"), "error_status": res.get("error_status"), "message": msg or None,
            **({"name": res["json"]["name"]} if res.get("json") else {})}


out = {"robot_a": a.email, "robot_b": b.email}
out["B_get_folder_shared_only_with_A"] = norm(b.call(f"/files/{st['poc-main']}", F), st["poc-main"])
out["B_get_nonexistent_id"] = norm(b.call(f"/files/{fake}", F))
out["A_get_nonexistent_id"] = norm(a.call(f"/files/{fake}", F))
out["B_get_malformed_id_with_quote"] = norm(b.call("/files/abc'def", F))
out["B_list_children_of_A_folder"] = (lambda r: {"status": r["status"], "count": len(r.get("json", {}).get("files", [])), "reason": r.get("reason")})(
    b.call("/files", {"q": f"'{st['poc-main']}' in parents and trashed=false", "fields": "files(id)", "supportsAllDrives": "true"}))
out["B_list_children_of_fake_id"] = (lambda r: {"status": r["status"], "count": len(r.get("json", {}).get("files", [])), "reason": r.get("reason")})(
    b.call("/files", {"q": f"'{fake}' in parents and trashed=false", "fields": "files(id)", "supportsAllDrives": "true"}))
out["B_sharedWithMe"] = (lambda r: {"status": r["status"], "count": len(r.get("json", {}).get("files", []))})(
    b.call("/files", {"q": "sharedWithMe=true", "fields": "files(id)"}))
out["B_files_list_all"] = (lambda r: {"status": r["status"], "count": len(r.get("json", {}).get("files", []))})(
    b.call("/files", {"fields": "files(id)", "pageSize": 100}))
sp = b.call("/changes/startPageToken", {})
ch = b.call("/changes", {"pageToken": sp["json"]["startPageToken"], "fields": "changes(fileId)"})
out["B_changes_feed_empty_and_ok"] = {"startPageToken_status": sp["status"], "changes_status": ch["status"], "count": len(ch.get("json", {}).get("changes", []))}
# pasta publica ('qualquer pessoa com o link')
for who, rb in (("A", a), ("B", b)):
    g = rb.call(f"/files/{st['poc-link-public']}", F)
    out[f"{who}_get_public_link_folder"] = norm(g, st["poc-link-public"])
    ls = rb.call("/files", {"q": f"'{st['poc-link-public']}' in parents and trashed=false", "fields": "files(name)", "supportsAllDrives": "true"})
    out[f"{who}_list_public_link_children"] = {"status": ls["status"], "names": [f["name"] for f in ls.get("json", {}).get("files", [])]}
    out[f"{who}_public_in_sharedWithMe"] = any(f["name"] == "poc-link-public" for f in rb.call("/files", {"q": "sharedWithMe=true", "fields": "files(name)"}).get("json", {}).get("files", []))
# criterio: 404 de B para pasta de A identico ao de ID inexistente
x, y = out["B_get_folder_shared_only_with_A"], out["B_get_nonexistent_id"]
out["verdict_B_404_identical_to_nonexistent"] = {k: x[k] for k in ("status", "reason", "error_status", "message")} == {k: y[k] for k in ("status", "reason", "error_status", "message")}
print(save_result("m05-isolation", out))
print(json.dumps(out, indent=1, ensure_ascii=False))
