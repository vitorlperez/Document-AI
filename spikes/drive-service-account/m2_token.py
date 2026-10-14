"""Medicao 2: token via JWT bearer (drive.readonly): latencia, validade, clock skew, casos de erro."""
import statistics
import time
from email.utils import parsedate_to_datetime

from lib import Robot, save_result

r = Robot("a")
cold = []
for _ in range(5):
    res = r.raw_token_request()
    res.pop("_token", None)
    cold.append(res)
lat = [c["latency_ms"] for c in cold]

# uso do token + custo de reuso (cache)
tok = r.token()
t0 = time.perf_counter()
about = r.call("/about", {"fields": "user(emailAddress,kind),storageQuota"})
reuse_ms = round((time.perf_counter() - t0) * 1000)
user = (about.get("json") or {}).get("user", {})
google_date = parsedate_to_datetime(cold[0]["google_date_header"]).timestamp()

skew = {}
for label, kw in {
    "iat_futuro_+120s": {"iat_offset": 120},
    "iat_futuro_+330s": {"iat_offset": 330},
    "iat_futuro_+900s": {"iat_offset": 900},
    "iat_passado_-3000s_exp_ainda_valido": {"iat_offset": -3000},
    "ttl_3601s_(excede_1h)": {"ttl": 3601},
    "escopo_drive_file": {"scope": "https://www.googleapis.com/auth/drive.file"},
    "escopo_invalido": {"scope": "https://www.googleapis.com/auth/nao.existe"},
}.items():
    res = r.raw_token_request(**kw)
    res.pop("_token", None)
    skew[label] = {k: res[k] for k in ("status", "error", "error_description", "expires_in", "latency_ms")}

path = save_result("m02-token", {
    "robot": r.email, "scope": r.scope, "token_endpoint": r.token_uri,
    "cold_exchanges": [{k: c[k] for k in ("status", "latency_ms", "expires_in", "token_type")} for c in cold],
    "latency_ms": {"min": min(lat), "median": statistics.median(lat), "max": max(lat)},
    "token_fetches_in_session": r.token_fetches,
    "about_get": {"status": about["status"], "ms": reuse_ms, "robot_user_email": user.get("emailAddress"),
                  "storage_limit": (about.get("json") or {}).get("storageQuota", {}).get("limit")},
    "clock": {"local_minus_google_s": round(time.time() - google_date, 2)},
    "jwt_edge_cases": skew,
})
print(path)
