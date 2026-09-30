"""One retry/throttle policy for every remote source API (Drive, Graph, Notion, OCR)."""

import email.utils
import logging
import math
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

logger = logging.getLogger("document_intelligence.integration")
# Statuses that, once retries are exhausted, mean "try again later" rather than "broken".
_THROTTLE_STATUSES = frozenset({403, 429, 503})


class RemoteThrottled(RuntimeError):
    """The remote API kept throttling after the in-request retry budget."""

    def __init__(self, retry_after_seconds: float | None = None, *, reason: str = "throttled"):
        super().__init__("remote API throttling limit reached")
        self.retry_after_seconds = retry_after_seconds
        self.reason = reason


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """RFC 9110 §10.2.3: delay-seconds or an HTTP-date. Anything else is ignored."""
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - (now or datetime.now(UTC))).total_seconds()
    return max(0.0, seconds) if math.isfinite(seconds) else None


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5  # total tries, the first included
    base_delay: float = 1.0
    max_delay: float = 30.0  # cap for exponential backoff; Retry-After is authoritative
    max_total_wait: float = 90.0  # in-request budget; beyond it the caller releases the job
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class RemoteHttp:
    """Thread-safe: parallel extractors share one instance so a 429 slows all of them."""

    def __init__(
        self,
        *,
        policy: RetryPolicy = RetryPolicy(),
        min_interval_seconds: float = 0.0,
        is_retryable: Callable[[httpx.Response], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.policy = policy
        self.min_interval_seconds = min_interval_seconds
        self._is_retryable = is_retryable
        self._sleep, self._monotonic, self._jitter = sleep, monotonic, jitter
        self._lock = threading.Lock()
        self._not_before = 0.0
        self._blocked_until = 0.0

    def request(
        self, method: str, url: str, *, idempotent: bool = True, **kwargs: object
    ) -> httpx.Response:
        send = getattr(httpx, method.lower())  # module-level call: keeps existing monkeypatches valid
        waited = 0.0
        for attempt in range(self.policy.max_attempts):
            waited += self._wait_turn(self.policy.max_total_wait - waited)
            response = send(url, **kwargs)
            if not idempotent or not self._retryable(response):
                return response
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            delay = self._delay(attempt, retry_after)
            last = attempt == self.policy.max_attempts - 1
            if response.status_code in _THROTTLE_STATUSES:
                self._block_for(delay)
            if last or waited + delay > self.policy.max_total_wait:
                if response.status_code in _THROTTLE_STATUSES:
                    raise RemoteThrottled(retry_after, reason=f"http_{response.status_code}")
                return response  # 5xx: let the caller's raise_for_status describe it
            logger.warning(
                "remote request throttled; backing off",
                extra={
                    "event": "remote_http_retry",
                    "status": response.status_code,
                    "attempt": attempt + 1,
                    "delay_seconds": round(delay, 2),
                },
            )
            self._block_for(delay)
        raise AssertionError("retry loop must return or raise")  # pragma: no cover

    def _retryable(self, response: httpx.Response) -> bool:
        if response.status_code in self.policy.retry_statuses:
            return True
        return bool(self._is_retryable and self._is_retryable(response))

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        cap = min(self.policy.max_delay, self.policy.base_delay * (2**attempt))
        return cap * (0.5 + 0.5 * self._jitter())  # "equal jitter": never ~0, never a herd

    def _wait_turn(self, remaining_wait: float) -> float:
        with self._lock:
            now = self._monotonic()
            target = max(now, self._not_before, self._blocked_until)
            self._not_before = target + self.min_interval_seconds
        waited = 0.0
        while True:
            wait = max(0.0, target - now)
            if waited + wait > remaining_wait:
                raise RemoteThrottled(wait, reason="shared_gate")
            if wait:
                self._sleep(wait)
                waited += wait
            with self._lock:
                # A sibling may have extended the throttle while this call slept.
                if self._blocked_until <= target:
                    return waited
                now = max(target, self._monotonic())
                target = self._blocked_until
                self._not_before = max(self._not_before, target + self.min_interval_seconds)

    def _block_for(self, seconds: float) -> None:
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._monotonic() + seconds)
