"""Local build -> signed frontend -> ASGI integration. Simulated trusted edge only."""

import json
from pathlib import Path

import httpx

results = {"environment": "local only; simulated Railway X-Real-IP overwrite; fake WorkOS gateway"}
with httpx.Client(base_url="http://127.0.0.1:3118", timeout=10) as client:
    first = []
    for i in range(61):
        response = client.post("/api/auth/password", headers={"x-real-ip": "198.51.100.10", "x-forwarded-for": f"203.0.113.{i}", "x-auth-client-ip": "203.0.113.66", "x-auth-ip-signature": "forged"}, json={"email": f"attempt{i}@example.com", "password": "incorrect"})
        first.append(response.status_code)
    assert first[:60] == [400] * 60, first
    assert first[-1] == 429
    other = client.post("/api/auth/password", headers={"x-real-ip": "198.51.100.20"}, json={"email": "other@example.com", "password": "incorrect"})
    assert other.status_code == 400
    missing = client.post("/api/auth/password", json={"email": "missing@example.com", "password": "incorrect"})
    assert missing.status_code == 503
    session = client.get("/api/session")
    health = client.get("/api/health/live")
    me = client.get("/api/me")
    assert session.status_code == 200 and session.json() is None
    assert health.status_code == 200 and health.json() == {"status": "ok"}
    assert me.status_code == 401  # response reaches the API, not an ingress 503
    results["non_auth_without_ingress"] = {"session": session.status_code, "health": health.status_code, "me": me.status_code}
    results.update(client_one={"accepted_attempts": 60, "next_status": first[-1], "retry_after_present": bool(response.headers.get("retry-after"))}, client_two={"status": other.status_code}, forged_xff_and_context="overwritten; cannot rotate the first client's bucket", missing_trusted_ingress=missing.status_code)
with httpx.Client(base_url="http://127.0.0.1:8118", timeout=10) as client:
    forged = client.post("/auth/password", headers={"x-forwarded-for": "203.0.113.66", "x-real-ip": "203.0.113.66", "x-auth-client-ip": "203.0.113.66", "x-auth-ip-timestamp": "1", "x-auth-ip-signature": "forged"}, json={"email": "forged@example.com", "password": "incorrect"})
    assert forged.status_code == 403
    results["unsigned_direct_backend_request"] = forged.status_code
Path(__file__).with_name("proxy-smoke.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results))
