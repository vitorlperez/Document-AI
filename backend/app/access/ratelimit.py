"""Fixed-window rate limiting shared across API replicas through Redis."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class RateLimiter(Protocol):
    def hit(self, *, key: str, limit: int, window_seconds: int = 60) -> RateDecision: ...


def _decide(count: int, limit: int, window_seconds: int, now: float) -> RateDecision:
    reset = max(1, window_seconds - int(now % window_seconds))
    return RateDecision(count <= limit, limit, max(0, limit - count), reset)


class InMemoryRateLimiter:
    """Single-process limiter for tests and local development."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock, self._counts = clock, {}

    def hit(self, *, key: str, limit: int, window_seconds: int = 60) -> RateDecision:
        now = self._clock()
        bucket = (key, int(now // window_seconds))
        self._counts = {k: v for k, v in self._counts.items() if k[1] >= bucket[1]}
        self._counts[bucket] = self._counts.get(bucket, 0) + 1
        return _decide(self._counts[bucket], limit, window_seconds, now)


class RedisRateLimiter:
    def __init__(self, client, prefix: str = "rl"):
        self._client, self._prefix = client, prefix

    def hit(self, *, key: str, limit: int, window_seconds: int = 60) -> RateDecision:
        now = time.time()
        redis_key = f"{self._prefix}:{key}:{int(now // window_seconds)}"
        pipeline = self._client.pipeline()
        pipeline.incr(redis_key)
        pipeline.expire(redis_key, window_seconds + 1)
        count, _ = pipeline.execute()
        return _decide(int(count), limit, window_seconds, now)
