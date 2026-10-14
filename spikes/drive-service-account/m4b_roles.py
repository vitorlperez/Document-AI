"""Medicao 4b: papel real do robo em cada pasta compartilhada + o escopo drive.readonly impede escrita mesmo com papel Editor?"""
import sys

TAG = sys.argv[1] if len(sys.argv) > 1 else "reader-mode"
from lib import Robot, load_state, mask_email, save_result

st = load_state()["folders"]
r = Robot("a")
out = {"robot": r.email, "folders": {}}
for name in ("poc-notify-on", "poc-notify-off", "poc-main", "arvore-1000", "poc-sem-download"):
    g = r.call(f"/files/{st[name]}", {"fields": "capabilities(canEdit,canComment,canDownload,canCopy,canShare,canAddChildren),permissions(type,role,emailAddress,permissionDetails)",
                                      "supportsAllDrives": "true"})
    j = g.get("json", {})
    robot_perm = [p for p in j.get("permissions", []) if (p.get("emailAddress") or "").startswith("arq-poc-a@")]
    out["folders"][name] = {"status": g["status"], "robot_role": [p["role"] for p in robot_perm],
                            "canEdit": j.get("capabilities", {}).get("canEdit"), "canComment": j.get("capabilities", {}).get("canComment"),
                            "canDownload": j.get("capabilities", {}).get("canDownload"), "canCopy": j.get("capabilities", {}).get("canCopy"),
                            "permissions_visible": len(j.get("permissions", []))}
    print(name, out["folders"][name])
# tentativa de escrita com escopo drive.readonly (papel pode ser Editor): deve falhar
w = r.call("/files", method="POST", body={"name": "NAO-DEVE-EXISTIR.txt", "parents": [st["poc-notify-off"]]},
           params={"supportsAllDrives": "true", "fields": "id"})
out["write_attempt_with_readonly_scope"] = {"status": w["status"], "reason": w.get("reason"), "message": w.get("message")}
print(out["write_attempt_with_readonly_scope"])
print(save_result(f"m04b-roles-and-scope-{TAG}", out))
