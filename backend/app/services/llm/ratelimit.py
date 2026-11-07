"""Client-side tokens-per-minute pacing (Groq free tier: about 8K TPM for gpt-oss-120b).

Before a request, the client reserves its estimated tokens; if the last 60 seconds plus this
request would exceed the limit, it waits until enough of the window has passed. After the
request, the reservation is corrected to the real token count. Groq's own 429 + Retry-After
(handled by the client's retries) remains the backstop if the estimate is off.

A request bigger than the whole limit is allowed when the window is empty: the provider then
decides, and its error is reported clearly instead of waiting forever.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

CHARS_PER_TOKEN = 4  # rough average for English text; used only for pacing, never for billing
WINDOW_SEC = 60.0


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    return sum(len(m.get("content", "")) // CHARS_PER_TOKEN + 4 for m in messages)


class Reservation:
    __slots__ = ("t", "tokens")

    def __init__(self, t: float, tokens: int) -> None:
        self.t = t
        self.tokens = tokens


class TokenRateLimiter:
    def __init__(
        self,
        tokens_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limit = tokens_per_minute
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._events: deque[Reservation] = deque()

    def acquire(self, tokens: int) -> tuple[Reservation | None, float]:
        """Block until `tokens` fit in the current minute. Returns (reservation, seconds waited)."""
        if self.limit <= 0:
            return None, 0.0
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                while self._events and now - self._events[0].t >= WINDOW_SEC:
                    self._events.popleft()
                used = sum(e.tokens for e in self._events)
                if not self._events or used + tokens <= self.limit:
                    res = Reservation(now, tokens)
                    self._events.append(res)
                    return res, waited
                wait = max(0.05, self._events[0].t + WINDOW_SEC - now)
            self._sleep(wait)
            waited += wait

    def settle(self, reservation: Reservation | None, actual_tokens: int | None) -> None:
        """Replace the estimate with the provider's real count (if it reported one)."""
        if reservation is not None and actual_tokens is not None:
            with self._lock:
                reservation.tokens = actual_tokens
