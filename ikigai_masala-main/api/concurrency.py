"""
Concurrency control for CPU-heavy solver endpoints.

Provides a semaphore-based gate that limits how many menu-generation
requests can run at the same time.  Extra requests get an immediate
503 instead of queueing behind long-running solves.
"""

import functools
import threading

from flask import jsonify

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_CONCURRENT_SOLVES = 5

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_semaphore = threading.Semaphore(MAX_CONCURRENT_SOLVES)
_active = 0
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    """Return a snapshot of solver concurrency stats (for /health)."""
    with _lock:
        return {
            "active_solves": _active,
            "max_concurrent_solves": MAX_CONCURRENT_SOLVES,
        }


def solver_gate(fn):
    """Decorator that limits concurrent access to a Flask route.

    If all slots are taken, returns 503 with a user-friendly message.
    Otherwise, runs the wrapped handler while holding a semaphore slot.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global _active
        if not _semaphore.acquire(blocking=False):
            return jsonify({
                "success": False,
                "error": (
                    f"Server busy \u2014 {MAX_CONCURRENT_SOLVES} menus are "
                    "being generated. Please try again in a moment."
                ),
            }), 503

        with _lock:
            _active += 1
        try:
            return fn(*args, **kwargs)
        finally:
            with _lock:
                _active -= 1
            _semaphore.release()

    return wrapper
