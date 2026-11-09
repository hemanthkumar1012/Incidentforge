from __future__ import annotations

from forge.api.throttle import LoginThrottle


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_allows_until_user_limit_then_blocks() -> None:
    clock = Clock()
    t = LoginThrottle(per_user_limit=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert t.retry_after("alice") == 0
        t.record_failure("alice")
    assert 0 < t.retry_after("alice") <= 60
    assert t.retry_after("bob") == 0


def test_window_expiry_unblocks_and_reports_remaining() -> None:
    clock = Clock()
    t = LoginThrottle(per_user_limit=2, window_seconds=60, clock=clock)
    t.record_failure("a")
    clock.t += 10
    t.record_failure("a")
    assert t.retry_after("a") == 50
    clock.t += 51
    assert t.retry_after("a") == 0


def test_username_is_normalised() -> None:
    t = LoginThrottle(per_user_limit=1, clock=Clock())
    t.record_failure("Alice ")
    assert t.retry_after("alice") > 0


def test_global_limit_blocks_every_username() -> None:
    t = LoginThrottle(per_user_limit=100, global_limit=3, window_seconds=60, clock=Clock())
    for i in range(3):
        t.record_failure(f"user{i}")
    assert t.retry_after("someone-new") > 0


def test_success_clears_user_counter() -> None:
    t = LoginThrottle(per_user_limit=2, clock=Clock())
    t.record_failure("a")
    t.record_success("a")
    t.record_failure("a")
    assert t.retry_after("a") == 0
