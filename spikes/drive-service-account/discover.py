"""Guarda em ~/.config/arquivio-drive-poc/state.json os IDs das pastas de teste (vistos por sharedWithMe do robo A) + link publico."""
import sys

from lib import Robot, load_state, parse_drive_link, save_state

state = load_state()
r = Robot("a")
res = r.call("/files", {"q": "sharedWithMe=true and trashed=false", "pageSize": 100, "fields": "files(id,name)"})
state["folders"] = {f["name"]: f["id"] for f in res["json"]["files"]}
if len(sys.argv) > 1:
    p = parse_drive_link(sys.argv[1])
    state["folders"]["poc-link-public"] = p["id"]
    print("link publico parseado:", p["kind"])
save_state(state)
print(sorted(state["folders"]))
