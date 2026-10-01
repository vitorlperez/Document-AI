"""Ranged, verified download of big remote files into a temp file (no full body in memory)."""

import base64
import hashlib
import tempfile

import httpx
import pytest

from app.integrations.http import (
    DownloadIntegrityError,
    RemoteFileTooLarge,
    RemoteHttp,
    RetryPolicy,
    quick_xor_hash,
)

URL = "https://api.example.test/file"
DATA = bytes(range(256)) * 40  # 10 240 bytes
CHUNK = 4096


def http() -> RemoteHttp:
    return RemoteHttp(policy=RetryPolicy(max_attempts=2), sleep=lambda s: None)


class Server:
    """Fake origin honouring Range; `drop_at` = chunk offsets whose first attempt dies mid-way."""

    def __init__(self, data=DATA, *, ranges=True, drop_at=(), bad_range_at=(), wrong_status_at=()):
        self.data, self.ranges = data, ranges
        self.drop_at, self.bad_range_at, self.wrong_status_at = set(drop_at), set(bad_range_at), set(wrong_status_at)
        self.requests: list[str | None] = []

    def __call__(self, url, **kwargs):
        rng = (kwargs.get("headers") or {}).get("Range")
        self.requests.append(rng)
        request = httpx.Request("GET", url)
        if rng is None or not self.ranges:
            return httpx.Response(200, content=self.data, request=request)
        start, end = (int(x) for x in rng.removeprefix("bytes=").split("-"))
        if start in self.drop_at:
            self.drop_at.discard(start)
            raise httpx.ReadError("connection dropped")
        if start in self.wrong_status_at:
            return httpx.Response(200, content=self.data, request=request)
        body = self.data[start:end + 1]
        first = start + 1 if start in self.bad_range_at else start
        return httpx.Response(206, content=body, request=request, headers={
            "Content-Range": f"bytes {first}-{start + len(body) - 1}/{len(self.data)}"})


def run(monkeypatch, server, **kwargs):
    monkeypatch.setattr(httpx, "get", server)
    with tempfile.TemporaryFile() as dest:
        http().download_to(URL, dest, chunk_size=CHUNK, **kwargs)
        dest.seek(0)
        return dest.read()


def test_downloads_in_206_chunks_and_reassembles(monkeypatch):
    server = Server()
    assert run(monkeypatch, server) == DATA
    assert server.requests == ["bytes=0-4095", "bytes=4096-8191", "bytes=8192-12287"]


def test_known_size_skips_the_probe_and_verifies_md5(monkeypatch):
    server = Server()
    assert run(monkeypatch, server, expected_size=len(DATA), hashes={"md5": hashlib.md5(DATA).hexdigest()}) == DATA


def test_server_without_range_support_falls_back_to_a_single_download(monkeypatch):
    server = Server(ranges=False)
    assert run(monkeypatch, server) == DATA
    assert len(server.requests) == 1


def test_a_dropped_connection_retries_only_that_chunk(monkeypatch):
    server = Server(drop_at=[4096])
    assert run(monkeypatch, server) == DATA
    assert server.requests.count("bytes=4096-8191") == 2 and server.requests.count("bytes=0-4095") == 1


def test_200_in_the_middle_or_a_wrong_content_range_is_not_accepted(monkeypatch):
    with pytest.raises(DownloadIntegrityError):
        run(monkeypatch, Server(bad_range_at=[4096]))
    with pytest.raises(DownloadIntegrityError):
        run(monkeypatch, Server(wrong_status_at=[4096]))


def test_size_mismatch_is_an_integrity_error(monkeypatch):
    with pytest.raises(DownloadIntegrityError):
        run(monkeypatch, Server(), expected_size=len(DATA) + 1)


def test_hash_mismatch_is_an_integrity_error(monkeypatch):
    with pytest.raises(DownloadIntegrityError):
        run(monkeypatch, Server(), hashes={"md5": "0" * 32})
    with pytest.raises(DownloadIntegrityError):
        run(monkeypatch, Server(), hashes={"sha1": "0" * 40})


def test_quick_xor_hash_is_checked_when_present(monkeypatch):
    good = base64.b64encode(quick_xor_hash(DATA)).decode()
    assert run(monkeypatch, Server(), hashes={"quickxor": good}) == DATA


def test_quick_xor_known_properties():
    assert len(quick_xor_hash(b"")) == 20 and quick_xor_hash(b"") == bytes(20)
    assert quick_xor_hash(b"a") != quick_xor_hash(b"b")
    assert quick_xor_hash(b"a" * 100) == quick_xor_hash(b"a" * 100)


def test_max_bytes_is_enforced_before_downloading_the_rest(monkeypatch):
    server = Server()
    monkeypatch.setattr(httpx, "get", server)
    with tempfile.TemporaryFile() as dest, pytest.raises(RemoteFileTooLarge):
        http().download_to(URL, dest, chunk_size=CHUNK, max_bytes=5000)
    assert len(server.requests) == 1


def test_non_success_status_goes_to_the_error_hook(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(403, request=httpx.Request("GET", url)))

    class Boom(Exception):
        pass

    def on_error(response):
        calls.append(response.status_code)
        raise Boom()

    with tempfile.TemporaryFile() as dest, pytest.raises(Boom):
        http().download_to(URL, dest, chunk_size=CHUNK, on_error=on_error)
    assert calls == [403]


# ---- provider clients -------------------------------------------------------------------------


def _drive_client():
    from app.integrations.google_drive import GoogleDriveOAuthClient

    return GoogleDriveOAuthClient(client_id=None, client_secret=None, redirect_uri=None, http=http())


def test_drive_media_download_is_ranged_and_md5_verified(monkeypatch):
    from app.integrations.google_drive import GoogleCredentials, RemoteFile

    server = Server()
    monkeypatch.setattr(httpx, "get", server)
    remote = RemoteFile("id", "a.pdf", "application/pdf", "", None, size=len(DATA), md5=hashlib.md5(DATA).hexdigest())
    content = _drive_client().read_file(credentials=GoogleCredentials("t", "r", None), remote_file=remote)
    assert content.read() == DATA and len(server.requests) >= 1 and all(r for r in server.requests)
    bad = RemoteFile("id", "a.pdf", "application/pdf", "", None, size=len(DATA), md5="0" * 32)
    with pytest.raises(DownloadIntegrityError):
        _drive_client().read_file(credentials=GoogleCredentials("t", "r", None), remote_file=bad)


def test_drive_native_export_is_a_single_download_without_range(monkeypatch):
    from app.integrations.google_drive import GoogleCredentials, RemoteFile

    server = Server(b"exported text")
    monkeypatch.setattr(httpx, "get", server)
    remote = RemoteFile("id", "doc", "application/vnd.google-apps.document", "", None)
    content = _drive_client().read_file(credentials=GoogleCredentials("t", "r", None), remote_file=remote)
    assert content.read() == b"exported text" and server.requests == [None]


def test_graph_download_is_ranged_and_sha1_verified(monkeypatch):
    from app.integrations.onedrive import MicrosoftGraphClient, OneDriveCredentials

    server = Server()
    monkeypatch.setattr(httpx, "get", server)
    client = MicrosoftGraphClient(client_id=None, client_secret=None, redirect_uri=None, http=http())
    credentials = OneDriveCredentials("t", "r", None)
    content = client.read_file(credentials=credentials, item_id="abc", size=len(DATA),
                               hashes={"sha1": hashlib.sha1(DATA).hexdigest().upper()})
    assert content.read() == DATA and all(server.requests)
