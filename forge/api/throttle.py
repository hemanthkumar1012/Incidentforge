"""In-process login throttle.

Failed logins are counted per username and globally inside a sliding window. Once a
limit is hit, further attempts are refused until the oldest failure ages out. State is
per process: run a single forge-api replica, or front it with a shared limiter. The
client IP is deliberately not a key, because behind the Vercel proxy it is not reliable.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class LoginThrottle:
    def __init__(
        self,
        *,
        per_user_limit: int = 5,
        global_limit: int = 50,
        window_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_user_limit = per_user_limit
        self.global_limit = global_limit
        self.window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._by_user: dict[str, deque[float]] = defaultdict(deque)
        self._all: deque[float] = deque()

    @staticmethod
    def _key(username: str) -> str:
        return username.strip().lower()[:64]

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] >= self.window:
            q.popleft()

    def retry_after(self, username: str) -> int:
        """Seconds to wait before another attempt, or 0 if the attempt is allowed."""
        now = self._clock()
        key = self._key(username)
        with self._lock:
            user_q = self._by_user[key]
            self._prune(user_q, now)
            self._prune(self._all, now)
            waits = []
            if len(user_q) >= self.per_user_limit:
                waits.append(self.window - (now - user_q[0]))
            if len(self._all) >= self.global_limit:
                waits.append(self.window - (now - self._all[0]))
            if not user_q:
                self._by_user.pop(key, None)
            return int(max(waits) + 0.999) if waits else 0

    def record_failure(self, username: str) -> None:
        now = self._clock()
        with self._lock:
            self._by_user[self._key(username)].append(now)
            self._all.append(now)
            if len(self._all) > self.global_limit * 4:
                self._all.popleft()

    def record_success(self, username: str) -> None:
        with self._lock:
            self._by_user.pop(self._key(username), None)
