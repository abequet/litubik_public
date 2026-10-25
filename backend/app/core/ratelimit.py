# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""L2: online brute-force protection for the login endpoint.

An in-memory, per-(IP, account) counter: after MAX_FAILURES consecutive failed
logins the pair is locked for COOLDOWN_SECONDS. A successful login clears it.
In-memory is sufficient for the mono-process server (a restart simply resets the
counters, which is safe — it never *grants* access, only delays it).
"""
import threading
import time

MAX_FAILURES = 3
COOLDOWN_SECONDS = 10 * 60  # 10 minutes


class LoginThrottle:
    def __init__(self, max_failures: int = MAX_FAILURES,
                 cooldown: int = COOLDOWN_SECONDS):
        self.max_failures = max_failures
        self.cooldown = cooldown
        self._lock = threading.Lock()
        # key -> (failure_count, locked_until_epoch)
        self._state: dict[str, tuple[int, float]] = {}

    def retry_after(self, key: str) -> int:
        """Seconds the caller must wait, or 0 if not currently locked."""
        with self._lock:
            entry = self._state.get(key)
            if not entry:
                return 0
            _, locked_until = entry
            remaining = locked_until - time.monotonic()
            return int(remaining) + 1 if remaining > 0 else 0

    def record_failure(self, key: str) -> None:
        with self._lock:
            count, locked_until = self._state.get(key, (0, 0.0))
            now = time.monotonic()
            if locked_until and now >= locked_until:
                count = 0  # a previous lock expired -> start a fresh window
            count += 1
            locked_until = (now + self.cooldown
                            if count >= self.max_failures else 0.0)
            self._state[key] = (count, locked_until)

    def reset(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)

    def clear(self) -> None:
        """Drop all counters (used by tests for isolation)."""
        with self._lock:
            self._state.clear()


login_throttle = LoginThrottle()


class SlidingWindowLimiter:
    """At most `limit` events per key within the last `window` seconds — used
    to bound how fast one address can open demo guest sessions. In memory
    only, like the login throttle: nothing about the caller is stored."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._lock = threading.Lock()
        self._events: dict[str, list[float]] = {}

    def hit(self, key: str) -> bool:
        """Record one event; False (and nothing recorded) when over the limit."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._events.get(key, ()) if now - t < self.window]
            if len(recent) >= self.limit:
                self._events[key] = recent
                return False
            recent.append(now)
            self._events[key] = recent
            # keep the table small: drop keys whose events all expired
            if len(self._events) > 10_000:
                self._events = {k: v for k, v in self._events.items()
                                if v and now - v[-1] < self.window}
            return True

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# demo guest sessions: 5 per address (an IPv6 /64) per hour, 20 per day, and
# 60 per hour for the whole instance — the last bound holds even against many
# addresses, so the live-session cap cannot be filled in a few minutes
guest_hourly = SlidingWindowLimiter(5, 3600)
guest_daily = SlidingWindowLimiter(20, 24 * 3600)
guest_global = SlidingWindowLimiter(60, 3600)
