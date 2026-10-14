"""Helpers do spike drive-service-account.

Regras: chave JSON do robo fica em ~/.config/arquivio-drive-poc/ (fora do repo); token, JWT e chave
privada NUNCA entram em log/resultado. Resultados guardam so codigos HTTP, motivos, contagens, tempos e nomes.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

CONFIG_DIR = Path.home() / ".config" / "arquivio-drive-poc"
RESULTS_DIR = Path(__file__).parent / "results"
STATE_FILE = CONFIG_DIR / "state.json"
DRIVE = "https://www.googleapis.com/drive/v3"
SCOPE_RO = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_RW = "https://www.googleapis.com/auth/drive"
TOKEN_HOST = "https://oauth2.googleapis.com/token"

_EMAIL = re.compile(r"([A-Za-z0-9])[A-Za-z0-9._+\-]*@")


def mask_email(value: str | None) -> str | None:
    return None if value is None else _EMAIL.sub(r"\1***@", value)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {}


def save_state(state: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    STATE_FILE.chmod(0o600)


def save_result(name: str, payload: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **payload}
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


class Robot:
    """Uma conta de servico: assina o JWT bearer e cacheia o access token."""

    def __init__(self, label: str, scope: str = SCOPE_RO) -> None:
        self.label = label
        self.scope = scope
        key = json.loads((CONFIG_DIR / f"sa-{label}.json").read_text())
        self.email: str = key["client_email"]
        self._pk: str = key["private_key"]
        self._kid: str = key["private_key_id"]
        self.token_uri: str = key["token_uri"]
        assert self.token_uri == TOKEN_HOST, "token_uri inesperado"
        self._token: str | None = None
        self._exp = 0.0
        self.token_fetches = 0
        self.http = httpx.Client(timeout=60)

    def assertion(self, iat_offset: int = 0, ttl: int = 3600, scope: str | None = None) -> str:
        now = int(time.time()) + iat_offset
        claims = {"iss": self.email, "scope": scope or self.scope, "aud": self.token_uri, "iat": now, "exp": now + ttl}
        return jwt.encode(claims, self._pk, algorithm="RS256", headers={"kid": self._kid})

    def raw_token_request(self, **kw: Any) -> dict[str, Any]:
        """Troca um JWT por token; devolve so metadados (nunca o token)."""
        t0 = time.perf_counter()
        r = self.http.post(
            self.token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": self.assertion(**kw)},
        )
        ms = round((time.perf_counter() - t0) * 1000)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        out: dict[str, Any] = {
            "status": r.status_code, "latency_ms": ms, "google_date_header": r.headers.get("date"),
            "error": body.get("error"), "error_description": body.get("error_description"),
            "expires_in": body.get("expires_in"), "token_type": body.get("token_type"),
            "has_access_token": "access_token" in body,
        }
        if "access_token" in body:
            out["_token"] = body["access_token"]
        return out

    def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        res = self.raw_token_request()
        if res["status"] != 200:
            raise RuntimeError(f"token falhou: {res['status']} {res.get('error')}")
        self._token = res["_token"]
        self._exp = time.time() + int(res["expires_in"])
        self.token_fetches += 1
        return self._token

    def call(self, path: str, params: dict[str, Any] | None = None, method: str = "GET", body: Any = None,
             raw: bool = False, url: str | None = None, retries: int = 4) -> dict[str, Any]:
        """Chamada a Drive v3 com backoff simples; devolve status/reason/ms/json ou bytes/sha."""
        attempt = 0
        while True:
            t0 = time.perf_counter()
            r = self.http.request(method, url or f"{DRIVE}{path}", params=params, json=body,
                                  headers={"Authorization": f"Bearer {self.token()}"})
            ms = round((time.perf_counter() - t0) * 1000)
            out: dict[str, Any] = {"status": r.status_code, "ms": ms}
            if r.status_code < 400:
                if raw:
                    out["bytes"] = len(r.content)
                    out["content_type"] = r.headers.get("content-type")
                    out["_content"] = r.content
                elif r.content:
                    out["json"] = r.json()
                return out
            try:
                err = r.json().get("error", {})
            except Exception:
                err = {}
            first = (err.get("errors") or [{}])[0]
            out.update(reason=first.get("reason"), message=err.get("message"), error_status=err.get("status"))
            retryable = r.status_code in (429, 500, 502, 503, 504) or (
                r.status_code == 403 and out["reason"] in ("rateLimitExceeded", "userRateLimitExceeded"))
            if retryable and attempt < retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 20))
                continue
            return out

    def close(self) -> None:
        self.http.close()


# ---------------------------------------------------------------- parser de links (medicao 13)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,128}$")
_PATTERNS = [
    ("folder", re.compile(r"^https?://drive\.google\.com/(?:a/[^/]+/)?drive/(?:u/\d+/|mobile/)?folders/([A-Za-z0-9_-]+)(?:[/?#].*)?$")),
    ("folder", re.compile(r"^https?://drive\.google\.com/(?:a/[^/]+/)?folderview\?(?:[^#]*&)?id=([A-Za-z0-9_-]+)(?:[&#].*)?$")),
    ("ambiguous", re.compile(r"^https?://drive\.google\.com/(?:a/[^/]+/)?open\?(?:[^#]*&)?id=([A-Za-z0-9_-]+)(?:[&#].*)?$")),
    ("file", re.compile(r"^https?://drive\.google\.com/(?:a/[^/]+/)?file/d/([A-Za-z0-9_-]+)(?:[/?#].*)?$")),
    ("file", re.compile(r"^https?://docs\.google\.com/(?:document|spreadsheets|presentation|forms|drawings)/d/([A-Za-z0-9_-]+)(?:[/?#].*)?$")),
]


def parse_drive_link(text: str) -> dict[str, str | None]:
    """Classifica o que o usuario colou. kind: folder|ambiguous|file|invalid. ambiguous => decidir por files.get(mimeType)."""
    value = text.strip()
    if ID_RE.match(value):
        return {"kind": "ambiguous", "id": value}
    for kind, rx in _PATTERNS:
        m = rx.match(value)
        if m and ID_RE.match(m.group(1)):
            return {"kind": kind, "id": m.group(1)}
    return {"kind": "invalid", "id": None}
