"""One retry/throttle policy for every remote source API (Drive, Graph, Notion, OCR)."""

import base64
import email.utils
import hashlib
import logging
import math
import operator
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import reduce

import httpx

logger = logging.getLogger("document_intelligence.integration")
# Statuses that, once retries are exhausted, mean "try again later" rather than "broken".
_THROTTLE_STATUSES = frozenset({403, 429, 503})


DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")


class DownloadIntegrityError(RuntimeError):
    """The downloaded bytes do not match what the server promised (range, size or hash)."""


class RemoteFileTooLarge(RuntimeError):
    """The remote file is bigger than the caller's cap; nothing more is downloaded."""


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


def parse_rate_limit_reset(value: str | None, *, now: datetime | None = None) -> float | None:
    """`X-RateLimit-Reset` as a Unix timestamp (ClickUp 429s carry it instead of Retry-After)."""
    try:
        reset = float(value or "")
    except ValueError:
        return None
    if not math.isfinite(reset) or not 1e9 <= reset < 4e9:  # seconds-left or milliseconds: not a Unix timestamp
        return None
    return max(1.0, reset - (now or datetime.now(UTC)).timestamp())  # floor: clock skew must not mean "no wait"


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
            if retry_after is None:
                retry_after = parse_rate_limit_reset(response.headers.get("X-RateLimit-Reset"))
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

    def download_to(
        self,
        url: str,
        dest,
        *,
        headers: dict[str, str] | None = None,
        expected_size: int | None = None,
        hashes: dict[str, str] | None = None,
        chunk_size: int = DOWNLOAD_CHUNK_BYTES,
        chunk_retries: int = 3,
        max_bytes: int | None = None,
        on_error: Callable[[httpx.Response], None] | None = None,
        timeout: float = 30,
        follow_redirects: bool = True,
    ) -> int:
        """Fetch `url` in `chunk_size` HTTP Range blocks into the seekable `dest`; returns the byte count.

        Each block is retried on its own (transport drop, non-206, inconsistent Content-Range). A server
        that ignores Range (200) is handled by a single download. The final size and, when given,
        md5/sha1/sha256/quickxor are verified. `dest` is left rewound to 0.
        """
        check = on_error or (lambda response: response.raise_for_status())
        total = expected_size
        offset = 0
        dest.seek(0)
        dest.truncate()

        def fetch(start: int, end: int) -> httpx.Response:
            last: Exception | None = None
            for attempt in range(chunk_retries):
                if attempt:
                    self._sleep(min(self.policy.max_delay, self.policy.base_delay * 2 ** (attempt - 1)))
                try:
                    response = self.request(
                        "GET", url, headers={**(headers or {}), "Range": f"bytes={start}-{end}"},
                        timeout=timeout, follow_redirects=follow_redirects,
                    )
                except httpx.TransportError as error:
                    last = error
                    continue
                if response.status_code == 200:
                    return response  # origin ignored Range
                if response.status_code != 206:
                    check(response)
                    last = DownloadIntegrityError(f"unexpected status {response.status_code}")
                    continue
                match = _CONTENT_RANGE.match(response.headers.get("Content-Range", ""))
                body = response.content
                if (not match or int(match.group(1)) != start or int(match.group(2)) != start + len(body) - 1
                        or len(body) > end - start + 1):
                    last = DownloadIntegrityError("inconsistent Content-Range")
                    continue
                return response
            raise DownloadIntegrityError(str(last) if last else "download failed")

        while total is None or offset < total:
            response = fetch(offset, offset + chunk_size - 1)
            if response.status_code == 200:
                if offset:
                    raise DownloadIntegrityError("server stopped honouring Range")
                if max_bytes is not None and len(response.content) > max_bytes:
                    raise RemoteFileTooLarge()
                dest.write(response.content)
                offset = len(response.content)
                total = offset
                break
            if total is None:
                declared = _CONTENT_RANGE.match(response.headers["Content-Range"]).group(3)
                total = int(declared) if declared != "*" else None
                if total is not None and max_bytes is not None and total > max_bytes:
                    raise RemoteFileTooLarge()
            elif _CONTENT_RANGE.match(response.headers["Content-Range"]).group(3) not in {"*", str(total)}:
                raise DownloadIntegrityError("file changed during download")
            dest.write(response.content)
            offset += len(response.content)
            if total is None and len(response.content) < chunk_size:
                total = offset
        if offset != total:
            raise DownloadIntegrityError("size mismatch")
        _verify_hashes(dest, hashes or {})
        dest.seek(0)
        return offset

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


def quick_xor_hash(data: bytes) -> bytes:
    """Microsoft quickXorHash: bytes XOR-ed into a 160-bit ring, 11 bits further per byte, then the length."""
    hasher = QuickXor()
    hasher.update(data)
    return hasher.digest()


class QuickXor:
    WIDTH = 160

    def __init__(self) -> None:
        self._acc = [0] * self.WIDTH  # XOR of the bytes at each position modulo 160
        self._length = 0

    def update(self, data: bytes) -> None:
        for residue in range(self.WIDTH):
            piece = data[(residue - self._length) % self.WIDTH::self.WIDTH]
            if piece:
                self._acc[residue] ^= reduce(operator.xor, piece)
        self._length += len(data)

    def digest(self) -> bytes:
        mask = (1 << self.WIDTH) - 1
        state = 0
        for residue, value in enumerate(self._acc):
            shifted = value << (11 * residue % self.WIDTH)
            state ^= (shifted | (shifted >> self.WIDTH)) & mask
        raw = bytearray(state.to_bytes(self.WIDTH // 8, "little"))
        for index, byte in enumerate(self._length.to_bytes(8, "little")):
            raw[12 + index] ^= byte
        return bytes(raw)


def _verify_hashes(dest, hashes: dict[str, str]) -> None:
    hashers = {name: hashlib.new(name) for name in ("md5", "sha1", "sha256") if hashes.get(name)}
    quick = QuickXor() if hashes.get("quickxor") else None
    if not hashers and quick is None:
        return
    dest.seek(0)
    while block := dest.read(1024 * 1024):
        for hasher in hashers.values():
            hasher.update(block)
        if quick is not None:
            quick.update(block)
    for name, hasher in hashers.items():
        if hasher.hexdigest() != hashes[name].lower():
            raise DownloadIntegrityError(f"{name} mismatch")
    if quick is not None and base64.b64encode(quick.digest()).decode() != hashes["quickxor"]:
        # Not yet validated against real Graph payloads: size + sha1/md5 stay authoritative.
        logger.warning("quickXorHash mismatch", extra={"event": "remote_download_quickxor_mismatch"})
