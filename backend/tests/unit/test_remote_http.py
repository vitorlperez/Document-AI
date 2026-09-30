"""Retry, Retry-After and pacing shared by every remote source client."""

from datetime import UTC, datetime

import httpx
import pytest

from app.integrations.http import RemoteHttp, RemoteThrottled, RetryPolicy, parse_retry_after

URL = "https://api.example.test/x"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 6))
        self.now += seconds


def reply(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers or {}, request=httpx.Request("GET", URL))


def script(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response) -> list[dict]:
    queue, calls = list(responses), []

    def fake(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return queue.pop(0)

    monkeypatch.setattr(httpx, "get", fake)
    monkeypatch.setattr(httpx, "post", fake)
    return calls


def http(clock: Clock, **kwargs: object) -> RemoteHttp:
    return RemoteHttp(sleep=clock.sleep, monotonic=clock.monotonic, jitter=lambda: 1.0, **kwargs)


def test_parse_retry_after_accepts_seconds_and_http_dates_and_rejects_garbage() -> None:
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("2", now=now) == 2.0
    assert parse_retry_after("Tue, 29 Sep 2026 12:00:07 GMT", now=now) == 7.0
    assert parse_retry_after("Tue, 29 Sep 2026 11:00:00 GMT", now=now) == 0.0
    for bad in (None, "", "soon", "nan", "inf"):
        assert parse_retry_after(bad, now=now) is None


def test_429_with_retry_after_waits_that_long_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    calls = script(monkeypatch, reply(429, {"Retry-After": "2"}), reply(200))
    response = http(clock).request("GET", URL, headers={"A": "b"}, timeout=5)
    assert response.status_code == 200
    assert len(calls) == 2 and calls[0] == {"url": URL, "headers": {"A": "b"}, "timeout": 5}
    assert clock.slept == [2.0]


def test_exhausted_throttling_raises_with_the_last_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    script(monkeypatch, *[reply(429, {"Retry-After": "4"})] * 3)
    with pytest.raises(RemoteThrottled) as caught:
        http(clock, policy=RetryPolicy(max_attempts=3)).request("GET", URL, timeout=5)
    assert caught.value.retry_after_seconds == 4.0 and clock.slept == [4.0, 4.0]


def test_wait_budget_stops_before_sleeping_for_a_very_long_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    calls = script(monkeypatch, reply(429, {"Retry-After": "10"}))
    with pytest.raises(RemoteThrottled):
        http(clock, policy=RetryPolicy(max_total_wait=5.0)).request("GET", URL, timeout=5)
    assert len(calls) == 1 and clock.slept == []


def test_5xx_uses_capped_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    script(monkeypatch, reply(503), reply(503), reply(503), reply(200))
    policy = RetryPolicy(max_attempts=4, base_delay=1.0, max_delay=3.0)
    assert http(clock, policy=policy).request("GET", URL, timeout=5).status_code == 200
    assert clock.slept == [1.0, 2.0, 3.0]


def test_non_idempotent_requests_are_returned_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    calls = script(monkeypatch, reply(429))
    response = http(clock).request("POST", URL, idempotent=False, data={"a": "b"}, timeout=5)
    assert response.status_code == 429 and len(calls) == 1 and clock.slept == []


def test_custom_predicate_makes_a_403_quota_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    script(monkeypatch, reply(403), reply(200))
    client = http(clock, is_retryable=lambda response: response.status_code == 403)
    assert client.request("GET", URL, timeout=5).status_code == 200
    assert clock.slept == [1.0]


def test_a_retry_after_seen_by_one_caller_delays_every_other_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    client = http(clock)
    client._block_for(5.0)  # what a sibling thread does after receiving 429
    script(monkeypatch, reply(200))
    client.request("GET", URL, timeout=5)
    assert clock.slept == [5.0]


def test_min_interval_spaces_consecutive_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    script(monkeypatch, reply(200), reply(200))
    client = http(clock, min_interval_seconds=0.35)
    client.request("GET", URL, timeout=5)
    client.request("GET", URL, timeout=5)
    assert clock.slept == [0.35]


def test_retry_after_is_not_capped_below_the_servers_requested_delay(monkeypatch):
    clock = Clock()
    script(monkeypatch, reply(429, {"Retry-After": "60"}), reply(200))
    assert http(clock).request("GET", URL).status_code == 200
    assert clock.slept == [60.0]
