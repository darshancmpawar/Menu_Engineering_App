"""
In-process counter metrics.

Intentionally tiny — no dependency on prometheus_client / statsd, no
histograms, no gauges. Just monotonically-increasing counters behind a
lock, with an optional label dict that's flattened into a
``name{k=v,k2=v2}`` key. The goal is "have a number somewhere" so
the next person who wants to emit to Prometheus / Datadog has a
single place to swap implementations.

Usage:
    from api import metrics
    metrics.incr("plan_requests_total", status="success")
    metrics.incr("rule_failures_total", rule="cuisine")
    snapshot = metrics.snapshot()  # dict[str, int]

The snapshot is a sorted dict so JSON output is deterministic for
tests and for humans eyeballing /api/v1/metrics.
"""

from __future__ import annotations

import threading
from typing import Dict


_lock = threading.Lock()
_counters: Dict[str, int] = {}


def _format_key(name: str, labels: Dict[str, str]) -> str:
    if not labels:
        return name
    # Stable ordering keeps the snapshot keys deterministic regardless
    # of kwarg ordering at the call site.
    parts = ",".join(f'{k}="{labels[k]}"' for k in sorted(labels))
    return f"{name}{{{parts}}}"


def incr(name: str, amount: int = 1, **labels: str) -> None:
    """Bump ``name`` (with optional labels) by *amount*.

    Label values are cast to ``str`` so callers can pass numbers or
    enums without thinking about it. A zero or negative amount is
    silently ignored — counters are monotonic by definition.
    """
    if amount <= 0:
        return
    key = _format_key(name, {k: str(v) for k, v in labels.items()})
    with _lock:
        _counters[key] = _counters.get(key, 0) + amount


def snapshot() -> Dict[str, int]:
    """Return a point-in-time copy of every counter seen so far.

    Keys are sorted so the JSON surface is stable across processes
    and across runs (useful for snapshot-style tests).
    """
    with _lock:
        return {k: _counters[k] for k in sorted(_counters)}


def reset() -> None:
    """Clear all counters. Intended for tests only — production never
    needs to reset; counters are cheap and the process will restart."""
    with _lock:
        _counters.clear()
