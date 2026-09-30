import re

from app.access.keys import generate_api_key, split_api_key
from app.identity.auth import hash_secret


def test_generated_key_has_public_prefix_and_hashed_secret():
    key = generate_api_key()
    assert re.fullmatch(r"arq_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", key.raw)
    prefix, secret = split_api_key(key.raw)
    assert prefix == key.prefix and key.prefix.startswith("arq_")
    assert hash_secret(secret) == key.secret_hash and secret not in key.secret_hash


def test_keys_are_unique():
    assert len({generate_api_key().raw for _ in range(50)}) == 50


def test_malformed_keys_do_not_parse():
    for raw in ("", "arq_zzzzzzzz_" + "a" * 43, "sk_deadbeef_" + "a" * 43, "arq_deadbeef_short", "Bearer x"):
        assert split_api_key(raw) is None
