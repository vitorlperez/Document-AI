"""API key format: ``arq_<8 hex prefix>_<43-char urlsafe secret>``; only the secret's SHA-256 is stored."""

import re
import secrets
from dataclasses import dataclass

from app.identity.auth import hash_secret

KEY_PREFIX = "arq"
_KEY = re.compile(r"arq_([0-9a-f]{8})_([A-Za-z0-9_-]{32,})")


@dataclass(frozen=True)
class GeneratedKey:
    raw: str
    prefix: str
    secret_hash: str


def generate_api_key() -> GeneratedKey:
    prefix = f"{KEY_PREFIX}_{secrets.token_hex(4)}"
    secret = secrets.token_urlsafe(32)
    return GeneratedKey(raw=f"{prefix}_{secret}", prefix=prefix, secret_hash=hash_secret(secret))


def split_api_key(raw: str) -> tuple[str, str] | None:
    match = _KEY.fullmatch(raw.strip())
    return (f"{KEY_PREFIX}_{match.group(1)}", match.group(2)) if match else None
