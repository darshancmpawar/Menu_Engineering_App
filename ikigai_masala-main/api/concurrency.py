"""
Concurrency control for CPU-heavy solver endpoints.

Dynamic worker allocation tuned for 1 GB RAM:
  - 1 active solve  → 8 workers  (full CPU, best quality)
  - 2 active solves → 4 workers each
  - Max 2 running at once; extras queue and run next in line
"""

import functools
import threading
from collections import deque

from flask import jsonify

# ---------------------------------------------------------------------------
# Configuration — tuned for 1 GB RAM
# ---------------------------------------------------------------------------
MAX_RUNNING = 2          # at most 2 solves executing simultaneously
MAX_QUEUED = 8           # max requests waiting in the pipeline
WORKERS_BY_LOAD = {      # active_count → CP-SAT workers per solve
    1: 9,
    2: 5,
}
DEFAULT_WORKERS = 2      # fallback (shouldn't happen with MAX_RUNNING=2)
QUEUE_TIMEOUT = 300      # seconds a queued request waits before giving up

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_running = 0
_queue: deque = deque()  # items are threading.Event objects


def _workers_for_current_load() -> int:
    """Return optimal CP-SAT worker count based on active solves."""
    return WORKERS_BY_LOAD.get(_running, DEFAULT_WORKERS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_worker_count() -> int:
    """Return the recommended CP-SAT worker count right now."""
    with _lock:
        return _workers_for_current_load()


def get_stats() -> dict:
    """Snapshot of concurrency stats (exposed via /health)."""
    with _lock:
        return {
            "active_solves": _running,
            "queued": len(_queue),
            "max_running": MAX_RUNNING,
            "max_queued": MAX_QUEUED,
            "workers_per_solve": _workers_for_current_load(),
        }


def solver_gate(fn):
    """Decorator: queues excess requests, rejects when pipeline is full.

    - If a slot is free → run immediately
    - If slots are full but queue has room → wait in line
    - If queue is full → 503
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global _running

        with _lock:
            if _running < MAX_RUNNING:
                _running += 1
                my_event = None
            elif len(_queue) < MAX_QUEUED:
                my_event = threading.Event()
                _queue.append(my_event)
            else:
                return jsonify({
                    "success": False,
                    "error": (
                        f"Server at capacity \u2014 {MAX_RUNNING} menus generating "
                        f"and {MAX_QUEUED} in queue. Please try again shortly."
                    ),
                }), 503

        # If queued, wait for our turn.
        if my_event is not None:
            got_slot = my_event.wait(timeout=QUEUE_TIMEOUT)
            if not got_slot:
                # Timeout expired. A releasing worker may have popped and
                # set() our event in the same instant — the wait() return
                # value lost that race. Re-check inside the lock: if the
                # event actually fired, we were already promoted to
                # "running" and must run fn() so the matching finally
                # block decrements _running. Otherwise, pull ourselves
                # out of the queue and return 504 cleanly.
                with _lock:
                    if my_event.is_set():
                        got_slot = True
                    else:
                        try:
                            _queue.remove(my_event)
                        except ValueError:
                            # Between wait() returning False and us
                            # taking the lock, another thread popped us.
                            # It has already incremented _running for
                            # us, so treat this as a late promotion.
                            got_slot = True
            if not got_slot:
                return jsonify({
                    "success": False,
                    "error": "Request timed out waiting in queue. Please try again.",
                }), 504

        try:
            return fn(*args, **kwargs)
        finally:
            with _lock:
                _running -= 1
                # Fill all available slots from the queue
                while _running < MAX_RUNNING and _queue:
                    next_event = _queue.popleft()
                    _running += 1
                    next_event.set()

    return wrapper
