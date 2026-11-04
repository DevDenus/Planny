import math
import time
from collections import deque
from collections.abc import Callable


class LoginRateLimiter:
    """A sliding window per IP, the outer layer in front of the backend's login-and-IP pause.

    It lives in memory on purpose: losing it on restart only forgets recent attempts.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._next_sweep = clock() + window_seconds

    def hit(self, key: str) -> int | None:
        """Counts an attempt. Returns seconds to wait if it is over the limit, otherwise None."""
        now = self._clock()
        self._sweep(now)
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return math.ceil(hits[0] + self._window - now)
        hits.append(now)
        return None

    def _sweep(self, now: float) -> None:
        """Drops idle addresses, otherwise the table would grow with every scanner."""
        if now < self._next_sweep:
            return
        self._next_sweep = now + self._window
        self._hits = {
            key: hits for key, hits in self._hits.items() if hits and hits[-1] > now - self._window
        }
