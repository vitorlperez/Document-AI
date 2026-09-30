import httpx
import pytest

from app.integrations.errors import SourceItemUnavailable
from app.integrations.google_drive import (
    GoogleCredentials,
    GoogleDriveOAuthClient,
    GoogleRemoteUnauthorized,
    RemoteFile,
    google_error_reason,
)
from app.integrations.http import RemoteHttp, RemoteThrottled, RetryPolicy

CREDS = GoogleCredentials("access", "refresh", None)
FILE = RemoteFile("f1", "a.pdf", "application/pdf", "https://drive.example.test/f1", None)


def drive_error(status: int, reason: str | None = None, *, details: bool = False) -> httpx.Response:
    body: dict = {"error": {"code": status}}
    if reason and details:
        body["error"]["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    elif reason:
        body["error"]["errors"] = [{"reason": reason}]
    return httpx.Response(status, json=body, request=httpx.Request("GET", "https://www.googleapis.com/drive/v3/x"))


def client(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response):
    queue, slept, calls = list(responses), [], []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: (calls.append(url), queue.pop(0))[1])
    http = RemoteHttp(
        policy=RetryPolicy(max_attempts=3), sleep=slept.append, monotonic=lambda: 0.0, jitter=lambda: 1.0,
        is_retryable=lambda r: r.status_code == 403 and google_error_reason(r) in {
            "rateLimitExceeded", "userRateLimitExceeded", "sharingRateLimitExceeded"},
    )
    return GoogleDriveOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb", http=http), calls, slept


def test_reason_is_read_from_legacy_errors_and_from_error_details() -> None:
    assert google_error_reason(drive_error(403, "userRateLimitExceeded")) == "userRateLimitExceeded"
    assert google_error_reason(drive_error(403, "rateLimitExceeded", details=True)) == "rateLimitExceeded"
    assert google_error_reason(httpx.Response(403, request=httpx.Request("GET", "https://x"))) is None


def test_quota_403_is_retried_and_never_becomes_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = httpx.Response(200, json={"files": []}, request=httpx.Request("GET", "https://x"))
    api, calls, _ = client(monkeypatch, drive_error(403, "userRateLimitExceeded"), drive_error(403, "rateLimitExceeded"), ok)
    assert api.list_folders(credentials=CREDS) == [] and len(calls) == 3


def test_quota_403_that_never_recovers_is_throttled_not_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    api, calls, _ = client(monkeypatch, *[drive_error(403, "userRateLimitExceeded")] * 3)
    with pytest.raises(RemoteThrottled):
        api.list_folders(credentials=CREDS)
    assert len(calls) == 3


def test_daily_limit_is_not_retried_inside_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    api, calls, _ = client(monkeypatch, drive_error(403, "dailyLimitExceeded"))
    with pytest.raises(RemoteThrottled) as caught:
        api.list_folders(credentials=CREDS)
    assert caught.value.reason == "dailyLimitExceeded" and len(calls) == 1


def test_file_level_403_is_an_item_failure_not_a_source_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    api, _, _ = client(monkeypatch, drive_error(403, "insufficientFilePermissions"))
    with pytest.raises(SourceItemUnavailable):
        api.read_file(credentials=CREDS, remote_file=FILE)


@pytest.mark.parametrize("response", [httpx.Response(403, request=httpx.Request("GET", "https://x")), drive_error(401), drive_error(403, "forbidden")])
def test_bare_403_401_and_unknown_403_remain_unauthorized(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    api, _, _ = client(monkeypatch, response)
    with pytest.raises(GoogleRemoteUnauthorized):
        api.list_folders(credentials=CREDS)


def test_429_without_retry_after_backs_off_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = httpx.Response(200, json={"files": []}, request=httpx.Request("GET", "https://x"))
    api, calls, slept = client(monkeypatch, drive_error(429), ok)
    assert api.list_folders(credentials=CREDS) == [] and len(calls) == 2 and len(slept) == 1
