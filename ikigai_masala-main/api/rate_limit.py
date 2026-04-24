"""
Per-principal rate limiter.

Token bucket, in-memory, thread-safe. Bucket capacity and refill rate are
fixed per-decorator and intentionally small — the target is preventing a
single admin holding the login token from hammering /plan rather than a
general-purpose throttle. A future multi-process deployment should swap
this out for ``flask-limiter`` with a Redis backend; the decorator
interface stays stable.

Keys come from ``g.api_user['email']`` (populated by require_api_auth).
Requests that haven't passed auth fall back to ``remote_addr`` so the
decorator is still meaningful on routes we forget to gate — but the
common path is: auth runs first, so every limited request has a real
principal.
"""

from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict

from flask import g, jsonify, request

from api import metrics


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class _TokenBucketLimiter:
    """A single named token bucket shared across all principals.

    ``capacity`` is the burst allowance; ``refill_per_second`` is the
    long-run rate. Two admins each get their own bucket (keyed by
    email) — this class holds the whole map for one limit name.
    """

    def __init__(self, name: str, capacity: int, refill_per_second: float):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_second <= 0:
            raise ValueError("refill_per_second must be positive")
        self.name = name
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def try_acquire(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds).

        retry_after is 0 when allowed; otherwise the number of seconds
        the caller should wait before the bucket has at least one token
        again. Kept as a float for the 429 ``Retry-After`` header.
        """
        now = now if now is not None else time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, last_refill=now)
                self._buckets[key] = bucket
            # Refill since last touch, capped at capacity.
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(
                self.capacity,
                bucket.tokens + elapsed * self.refill_per_second,
            )
            bucket.last_refill = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0

            deficit = 1.0 - bucket.tokens
            retry_after = deficit / self.refill_per_second
            return False, retry_after

    def reset(self) -> None:
        """Clear all buckets. Tests only."""
        with self._lock:
            self._buckets.clear()


# Named limits the decorator can refer to by symbol. Tuned for the
# realistic humans-in-the-loop workload: an admin regenerating a day
# five times in a row should never hit a limit; an automated client
# looping on /plan definitely should.
_LIMITS: Dict[str, _TokenBucketLimiter] = {
    "plan": _TokenBucketLimiter(
        name="plan", capacity=10, refill_per_second=10 / 60.0,
    ),  # 10 per minute, burst 10
    "regenerate": _TokenBucketLimiter(
        name="regenerate", capacity=20, refill_per_second=20 / 60.0,
    ),  # 20 per minute, burst 20
}


def _principal_key() -> str:
    """Identity used as the bucket key for the current request."""
    api_user = getattr(g, "api_user", None) or {}
    email = api_user.get("email")
    if email:
        return f"user:{email}"
    # Pre-auth or public routes: fall back to IP so a lost decorator
    # still throttles anonymous hammering.
    return f"ip:{request.remote_addr or 'unknown'}"


def rate_limit(limit_name: str) -> Callable:
    """Decorate a route with one of the named limits.

    Place it *after* ``require_api_auth`` so ``g.api_user`` is populated
    before the bucket key is computed. Returns 429 with a
    ``Retry-After`` header when the bucket is empty.
    """
    limiter = _LIMITS[limit_name]

    def _wrap(fn):
        @functools.wraps(fn)
        def _inner(*args, **kwargs):
            key = _principal_key()
            allowed, retry_after = limiter.try_acquire(key)
            if allowed:
                metrics.incr("rate_limit_allowed_total", limit=limit_name)
                return fn(*args, **kwargs)

            metrics.incr("rate_limit_rejected_total", limit=limit_name)
            retry_seconds = max(1, int(retry_after + 0.999))
            response = jsonify({
                "success": False,
                "error": (
                    f"Too many requests. Try again in "
                    f"~{retry_seconds}s."
                ),
                "retry_after_seconds": retry_seconds,
            })
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_seconds)
            return response
        return _inner
    return _wrap


def reset_for_tests() -> None:
    """Flush every named limiter. Tests only."""
    for limiter in _LIMITS.values():
        limiter.reset()
