"""A small in-process rate limiter.

One primitive, a sliding window over timestamps, used two ways:

    per-client   fairness -- one browser cannot monopolise a shared resource
    global       cost -- an absolute ceiling on how often we spend money

Both are needed, and the second matters more. `client_id()` is self-asserted:
the browser makes it up and sends it in a header, which is right for scoping
history and useless as a spending control, because anyone willing to rotate the
value gets a fresh per-client allowance every time. The global window is what
actually bounds the bill.

## What this is not

State lives in this process. Under gunicorn with N workers each keeps its own
counters, so the effective limit is N x what you configured. That is fine for a
cost *ceiling* set with headroom, and wrong for anything needing exactness --
quotas or billing want a shared store (Redis, the database). Same trade as the
job table in fashn_vton15_provider: honest note over a round-trip per call.

It is also not a security control. It slows down casual abuse and caps
accidental loops; it does not stop a determined attacker with many addresses.
"""
import collections
import threading
import time

# Stop the key table growing without bound when ids are rotated -- which is
# exactly what an abuser does. Eviction is oldest-activity-first.
_MAX_KEYS = 4096


class RateLimiter(object):
    """Allow `limit` hits per `per_seconds`, per key.

    Sliding window rather than fixed buckets: a fixed window lets someone spend
    the whole allowance at the end of one bucket and again at the start of the
    next, which for a limit of 1 per 60s means two spins a second apart.
    """

    def __init__(self, limit, per_seconds, max_keys=_MAX_KEYS):
        self.limit = max(1, int(limit))
        self.per_seconds = float(per_seconds)
        self.max_keys = max_keys
        self._hits = collections.OrderedDict()
        self._lock = threading.Lock()

    def check(self, key="*", now=None):
        """Record a hit if allowed.

        Returns (allowed, retry_after_seconds). retry_after is 0 when allowed,
        and otherwise how long until the oldest hit leaves the window.
        """
        now = time.time() if now is None else now
        cutoff = now - self.per_seconds

        with self._lock:
            window = self._hits.get(key)
            if window is None:
                window = collections.deque()
                self._hits[key] = window
            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= self.limit:
                return False, max(0.0, round(window[0] + self.per_seconds - now, 2))

            window.append(now)
            self._hits.move_to_end(key)
            self._evict()
            return True, 0.0

    def peek(self, key="*", now=None):
        """Remaining allowance without consuming any."""
        now = time.time() if now is None else now
        cutoff = now - self.per_seconds
        with self._lock:
            window = self._hits.get(key) or ()
            live = sum(1 for stamp in window if stamp > cutoff)
            return max(0, self.limit - live)

    def reset(self):
        with self._lock:
            self._hits.clear()

    def _evict(self):
        """Caller holds the lock."""
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)
