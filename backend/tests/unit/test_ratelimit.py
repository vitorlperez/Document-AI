from app.access.ratelimit import InMemoryRateLimiter


def test_window_allows_up_to_the_limit_then_blocks_with_reset():
    now = [1000.0]
    limiter = InMemoryRateLimiter(clock=lambda: now[0])
    decisions = [limiter.hit(key="k", limit=3, window_seconds=60) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert decisions[0].remaining == 2 and decisions[3].remaining == 0 and 0 < decisions[3].reset_seconds <= 60
    now[0] += 61
    assert limiter.hit(key="k", limit=3, window_seconds=60).allowed


def test_keys_are_independent():
    limiter = InMemoryRateLimiter()
    assert limiter.hit(key="a", limit=1).allowed and limiter.hit(key="b", limit=1).allowed
    assert not limiter.hit(key="a", limit=1).allowed
