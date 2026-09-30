"""Fernet keyring: the first key encrypts, every key may decrypt (rotation without downtime)."""

from collections.abc import Sequence

from cryptography.fernet import Fernet, MultiFernet


def build_fernet(keys: Sequence[str | None]) -> MultiFernet | None:
    usable = [key for key in keys if key]
    return MultiFernet([Fernet(key.encode()) for key in usable]) if usable else None


def rotate_token(fernet: MultiFernet, token: str) -> str:
    return fernet.rotate(token.encode()).decode()
