"""Capture the moments the solver quietly under-enforces a rule.

Sixteen places in the rule layer degrade rather than fail — a `min` capped to
what the pool can place, a per-day floor relaxed, a theme ban skipped because
the slot had nothing else to offer, a composition component dropped for want of
a cell, uniqueness dropped on a starved slot. Every one of them is the right
behaviour (design note 9c: the useful output is the conflict, not a plan that
abandoned the rules) and every one of them was written to a log nobody reads.

This module is the channel that carries them to a human. It has two halves and
they must stay together, which is why they share a file:

  * ``RELAXATION`` — the ``extra=`` key a rule stamps on its own log record.
  * ``RelaxationCapture`` — the handler that collects records carrying it.

**Why a stamped record rather than a log-level convention.** The obvious
implementation is "capture WARNING and above from ``src.menu_rules``". It does
not work: eleven of the sixteen relaxations are ``logger.info``, and three of
the WARNINGs in that tree are not relaxations at all (a malformed rule config
skipped at load time). Level does not separate the two populations, and matching
on message text would break the first time someone rewords a sentence. A field
on the record is the only signal that means exactly one thing.
``tests/explain/test_relaxations.py`` reads the AST and fails if a
relaxation-shaped log line is added without the stamp.

**Why the message-shape dedup.** Several of these fire per day: a 25-day plan
relaxing a daily floor emits 25 records differing only in the day index. A chef
needs to be told the floor was relaxed, once, with a count — not handed
twenty-five lines. ``record.msg`` is the *format string*, before interpolation,
so grouping on it groups by the thing that was relaxed with no parsing of the
rendered prose.

**Why it is thread-scoped.** ``@solver_gate`` runs two solves concurrently by
design (1 active -> 9 CP-SAT workers, 2 -> 5 each) and every handler attached to
a logger sees every record on it, so without a thread filter one request's
explanation would list another client's relaxations. Same hazard as design note
27, one layer up: shared per-process state written per request.

Never raises. A failure to describe a menu must not be a failure to plan one.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

# The `extra=` key. A rule stamps its own name here, so the handler learns both
# "this is a relaxation" and "which rule relaxed" from one field.
RELAXATION = 'menu_relaxation'

# The logger tree every rule module sits under (`src.menu_rules.<module>`).
RULES_LOGGER = 'src.menu_rules'

# Guards the shared logger's level across concurrent captures — see `_enable`.
_level_lock = threading.Lock()
_depth = 0                        # live captures
_saved_level = logging.NOTSET     # the level the FIRST of them found


def _enable() -> None:
    """Make INFO records reachable, remembering the level the first caller saw.

    ``logger.info(...)`` is dropped before any handler runs when the effective
    level is higher, so a deployment at WARNING would capture nothing at all —
    silently, which is the failure mode worth engineering against.

    Refcounted, with the original level held once rather than per instance: two
    overlapping captures each restoring "the level I saw on the way in" would
    leave the tree at INFO forever, because the second one saw the level the
    first had already lowered.
    """
    global _depth, _saved_level
    log = logging.getLogger(RULES_LOGGER)
    with _level_lock:
        if _depth == 0:
            _saved_level = log.level
            if not log.isEnabledFor(logging.INFO):
                log.setLevel(logging.INFO)
        _depth += 1


def _disable() -> None:
    global _depth
    log = logging.getLogger(RULES_LOGGER)
    with _level_lock:
        _depth = max(0, _depth - 1)
        if _depth == 0:                      # last one out restores the level
            log.setLevel(_saved_level)


class RelaxationCapture(logging.Handler):
    """Collect relaxation records emitted during one solve, on this thread.

    Use as a context manager::

        with RelaxationCapture() as cap:
            solver.solve()
        attach_relaxations(packs, cap.records)
    """

    def __init__(self) -> None:
        # INFO, not WARNING: eleven of the sixteen relaxation sites log at INFO.
        super().__init__(level=logging.INFO)
        self._by_shape: Dict[Any, Dict[str, Any]] = {}
        self._thread = threading.get_ident()

    # -- collection ---------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        rule = getattr(record, RELAXATION, None)
        if not rule:
            return
        if getattr(record, 'thread', None) != self._thread:
            return          # another request's solve, sharing this logger
        try:
            detail = record.getMessage()
        except Exception:                       # pragma: no cover - defensive
            return
        # Messages read "<rule name>: <what happened>". The name is a field of
        # its own here, so printing it twice helps nobody.
        prefix = f'{rule}: '
        if detail.startswith(prefix):
            detail = detail[len(prefix):]

        key = (str(rule), str(record.msg))
        entry = self._by_shape.get(key)
        if entry is None:
            self._by_shape[key] = {'rule': str(rule), 'detail': detail,
                                   'occurrences': 1}
        else:
            entry['occurrences'] += 1

    def handleError(self, record: logging.LogRecord) -> None:
        """Swallow. This layer describes a menu; it must never break one."""

    # -- results ------------------------------------------------------------

    @property
    def records(self) -> List[Dict[str, Any]]:
        """Relaxations, one per (rule, message shape), in the order first seen."""
        return [dict(v) for v in self._by_shape.values()]

    # -- lifecycle ----------------------------------------------------------

    def __enter__(self) -> 'RelaxationCapture':
        _enable()
        logging.getLogger(RULES_LOGGER).addHandler(self)
        return self

    def __exit__(self, *exc: Any) -> None:
        logging.getLogger(RULES_LOGGER).removeHandler(self)
        _disable()
        return None                    # never swallow the solve's own exception
