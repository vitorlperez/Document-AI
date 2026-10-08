"""Verify the actual Docker stack without remote authentication or email."""
import hashlib
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

base = Path(__file__).parent
before = json.loads((base / "before.json").read_text())
after = {}
safe = {}
for service in ["postgres", "redis", "worker", "beat", "api", "frontend"]:
    cid = subprocess.check_output(["docker", "compose", "ps", "-q", service], text=True).strip()
    item = json.loads(subprocess.check_output(["docker", "inspect", cid]))[0]
    after[service] = {
        "id": item["Id"], "startedAt": item["State"]["StartedAt"],
        "mounts": [{"name": m.get("Name"), "destination": m["Destination"]} for m in item["Mounts"]],
    }
    if service in ["postgres", "redis", "worker", "beat"]:
        assert after[service] == before[service], service
    env = dict(line.split("=", 1) for line in item["Config"]["Env"])
    if service == "api":
        assert all(hashlib.sha256(env.get(k, "").encode()).hexdigest() == value
                   for k, value in before["workosHashes"].items())
        safe = {k: v for k, v in env.items() if k.endswith("REDIRECT_URI") or k == "PUBLIC_APP_URL"}
        assert all(v.startswith("http://localhost:3000") for v in safe.values() if v), safe
        assert not item["HostConfig"]["PortBindings"], "API must stay internal"
    if service == "frontend":
        assert env["VITE_API_BASE_URL"] == "/api"
        assert env["API_UPSTREAM_URL"] == "http://api:8000"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


opener = urllib.request.build_opener(NoRedirect)
checks = []
for path, expected in [
    ("/", 200), ("/login", 200), ("/api/health/live", 200), ("/api/health/ready", 200),
    ("/api/session", 200), ("/api/me", 401),
    ("/api/auth/callback?code=local-smoke&state=invalid", 401), ("/api/auth/login", 302),
]:
    try:
        response = opener.open("http://localhost:3000" + path, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    assert response.status == expected, (path, response.status)
    body = response.read()
    check = {"path": path, "status": response.status}
    if path == "/api/session":
        assert json.loads(body) is None
    if path == "/api/auth/login":
        callback = urllib.parse.parse_qs(urllib.parse.urlsplit(response.headers["location"]).query)["redirect_uri"][0]
        assert callback == "http://localhost:3000/api/auth/callback", callback
        assert "HttpOnly" in response.headers["set-cookie"]
        check.update(redirectUri=callback, loginStateCookiePreserved=True)
    checks.append(check)

result = {
    "checks": checks, "safeLocalConfig": safe, "credentialsPreserved": True,
    "apiPortInternal": True, "unchangedServices": ["postgres", "redis", "worker", "beat"], "services": after,
}
(base / "runtime-checks.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "services"}, indent=2))
