"""Medicao 3 (+4): vigia `sharedWithMe` do robo e mede visibilidade = (primeira vez visto) - sharedWithMeTime (relogio do Google).

uso: python m3_watch.py <robo a|b> <segundos> [intervalo_s]
Salva results/m03-visibility-<robo>.json a cada novo item.
"""
import sys
import time
from datetime import datetime, timezone

from lib import Robot, mask_email, save_result

label, total = sys.argv[1], int(sys.argv[2])
interval = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
r = Robot(label)
seen: dict[str, dict] = {}
polls = 0
t_end = time.time() + total


def parse(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


while time.time() < t_end:
    now = time.time()
    res = r.call("/files", {"q": "sharedWithMe=true and trashed=false", "pageSize": 100, "supportsAllDrives": "true",
                            "includeItemsFromAllDrives": "true",
                            "fields": "files(id,name,mimeType,sharedWithMeTime,sharingUser(emailAddress),owners(emailAddress))"})
    polls += 1
    if res["status"] == 200:
        for f in res["json"].get("files", []):
            if f["id"] in seen:
                continue
            shared_at = parse(f["sharedWithMeTime"]) if f.get("sharedWithMeTime") else None
            seen[f["id"]] = {
                "name": f["name"], "mime": f["mimeType"], "id": f["id"],
                "first_seen_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
                "sharedWithMeTime": f.get("sharedWithMeTime"),
                "visible_after_s": None if shared_at is None else round(now - shared_at, 1),
                "sharingUser": mask_email((f.get("sharingUser") or {}).get("emailAddress")),
                "owner": mask_email(((f.get("owners") or [{}])[0]).get("emailAddress")),
            }
            print("NEW", f["name"], seen[f["id"]]["visible_after_s"], flush=True)
            save_result(f"m03-visibility-{label}", {"robot": r.email, "poll_interval_s": interval, "polls": polls, "items": list(seen.values())})
    else:
        print("poll status", res["status"], res.get("reason"), flush=True)
    time.sleep(interval)
save_result(f"m03-visibility-{label}", {"robot": r.email, "poll_interval_s": interval, "polls": polls, "items": list(seen.values())})
print("fim", polls)
