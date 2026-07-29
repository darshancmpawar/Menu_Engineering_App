"""
Per-client rate limiter.

Token bucket, in-memory, thread-safe. Bucket capacity and refill rate are
fixed per-decorator and intentionally small — the target is preventing a
single client from hammering /plan rather than a general-purpose throttle.
A future multi-process deployment should swap this out for
``flask-limiter`` with a Redis backend; the decorator interface stays
stable.

Keys come from the request's ``remote_addr`` so each client IP gets its
own bucket. (If something upstream ever populates ``g.api_user`` — e.g. a
future auth gateway — that identity takes precedence; see
``_principal_key``.)
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


# Named limits referenced by symbol from decorators / inline checks.
# Tuned for realistic humans-in-the-loop workloads: a user clicking
# through the planner should never hit these; an automated client
# looping on /plan definitely should.
_LIMITS: Dict[str, _TokenBucketLimiter] = {
    "plan": _TokenBucketLimiter(
        name="plan", capacity=10, refill_per_second=10 / 60.0,
    ),  # 10 per minute, burst 10
    "regenerate": _TokenBucketLimiter(
        name="regenerate", capacity=20, refill_per_second=20 / 60.0,
    ),  # 20 per minute, burst 20
    # Mutating endpoints (save / create / delete / config update). These were
    # unthrottled entirely, so a loop could hammer Supabase writes or mass-create
    # clients for free. Generous enough that an admin clicking through the editor
    # never notices.
    "write": _TokenBucketLimiter(
        name="write", capacity=30, refill_per_second=30 / 60.0,
    ),  # 30 per minute, burst 30
    # /diagnose runs the whole preprocessing + rule pass without solving, so it
    # is far from free even though it mutates nothing.
    "diagnose": _TokenBucketLimiter(
        name="diagnose", capacity=20, refill_per_second=20 / 60.0,
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


def check_rate_limit(limit_name: str, key: str):
    """Apply the named rate-limit bucket *limit_name* to *key* directly.

    Used by the :func:`rate_limit` decorator (which derives *key* via
    :func:`_principal_key`); also callable from non-decorator contexts
    that supply their own key.

    Returns:
        ``None`` when the request is allowed (caller proceeds normally),
        or a Flask 429 response object when the bucket is empty.
        The response carries an ``error`` message, a numeric
        ``retry_after_seconds`` field, and a standard ``Retry-After``
        header.

    The metrics-counter side-effects (``rate_limit_allowed_total`` /
    ``rate_limit_rejected_total``) match the decorator's behaviour, so
    Prometheus alerts on either work the same regardless of which
    surface tripped them.
    """
    if limit_name not in _LIMITS:
        raise KeyError(f"Unknown rate-limit bucket: {limit_name!r}")
    limiter = _LIMITS[limit_name]
    allowed, retry_after = limiter.try_acquire(key)
    if allowed:
        metrics.incr("rate_limit_allowed_total", limit=limit_name)
        return None

    metrics.incr("rate_limit_rejected_total", limit=limit_name)
    retry_seconds = max(1, int(retry_after + 0.999))
    response = jsonify({
        "success": False,
        "error": (
            f"Too many requests. Try again in ~{retry_seconds}s."
        ),
        "retry_after_seconds": retry_seconds,
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_seconds)
    return response


def rate_limit(limit_name: str) -> Callable:
    """Decorate a route with one of the named limits.

    The bucket key is the client IP (see :func:`_principal_key`).
    Returns 429 with a ``Retry-After`` header when the bucket is empty.
    Internally this just defers to :func:`check_rate_limit` so the
    decorator and any direct call site emit the same metrics and the
    same response shape.
    """

    def _wrap(fn):
        @functools.wraps(fn)
        def _inner(*args, **kwargs):
            rejection = check_rate_limit(limit_name, _principal_key())
            if rejection is not None:
                return rejection
            return fn(*args, **kwargs)
        return _inner
    return _wrap


def reset_for_tests() -> None:
    """Flush every named limiter. Tests only."""
    for limiter in _LIMITS.values():
        limiter.reset()
