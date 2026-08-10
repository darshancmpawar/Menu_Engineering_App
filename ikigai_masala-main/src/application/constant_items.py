"""Resolving a client's ``constant_items`` pins to real dishes.

Moved out of `api/app.py`, which had absorbed the application layer along with
the HTTP layer. Nothing here touches Flask or the database — it is a pure
function of a pin spec plus the ontology frame, which is why it belongs below the
interface rather than inside it.

A pin is honoured two ways, chosen by whether the dish exists in the ontology:
naming a real item narrows that cell's candidates so every other rule still sees
it (its colour counts toward colour variety, its cuisine toward cuisine variety);
naming a dish the city does not carry has nothing to narrow to, so the cell is
skipped and the text is stamped verbatim after the solve.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from src.constants import (
    BASE_SLOT_NAMES, CONST_SLOTS, MUTUALLY_EXCLUSIVE_SLOT_GROUPS,
)
from src.log_names import APP_LOGGER_NAME
from src.preprocessor.pool_builder import _base_slot

#: Not `__name__`. These warnings tell an operator their client config has a typo,
#: and they were emitted under `api.app` before this code moved out of the web
#: module — see src/log_names.py.
logger = logging.getLogger(APP_LOGGER_NAME)


def _exclusive_siblings(base_slot: str) -> Set[str]:
    """Base slots that cannot coexist with *base_slot* on one counter.

    ``curd`` and ``curd_side`` are the two yogurt-side categories: a counter
    serves one or the other, never both (see MUTUALLY_EXCLUSIVE_SLOT_GROUPS).
    """
    out: Set[str] = set()
    for group in MUTUALLY_EXCLUSIVE_SLOT_GROUPS:
        if base_slot in group:
            out |= set(group) - {base_slot}
    return out


def _slot_item_names(pools, base_slot):
    """Lowercased item names eligible for *base_slot*, from the built pools.

    The pre-filter chain (theme, cooldown, …) can still drop a dish later; the
    solver handles that case by solving the cell normally. This is the coarse
    "could this dish ever appear in this slot" test that decides force vs stamp.
    """
    pool = (pools or {}).get(base_slot)
    if pool is None or 'item' not in getattr(pool, 'columns', []):
        return frozenset()
    try:
        return frozenset(str(v).strip().lower() for v in pool['item'].tolist())
    except Exception:  # noqa: BLE001 — never break planning over a pin lookup
        return frozenset()


def _canonical_item_name(value, known_items):
    """Return the ontology spelling of *value*, or None if it is not a dish.

    Pins are hand-written, so ``"Boiled Egg"`` has to match ``boiled_egg``.
    """
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    if not name:
        return None
    for candidate in (name, name.replace(' ', '_')):
        if candidate in known_items:
            return candidate
    return None


def _validate_constant_values(client_name, resolved, df) -> None:
    """Warn about ``constant_items`` values that are not real dishes.

    A pinned value is free text written by hand, so a typo ships straight to
    the printed menu with nothing to catch it. Anything that does not resolve
    to an ontology item is logged once per (slot, value) — the pin is still
    honoured, because plenty of legitimate pins (``"Fish Masala"``,
    ``"Mutton Biryani"``) intentionally name dishes the veg-only ontology does
    not carry.

    Non-string values are reported too: ``_resolve_client_constant`` falls back
    to ``str(spec)``, so a stray number or nested object would otherwise print
    as ``"5"`` or a Python repr in the slot.
    """
    if df is None or 'item' not in getattr(df, 'columns', []):
        return
    try:
        known = {str(v).strip().lower() for v in df['item'].tolist()}
    except Exception:  # noqa: BLE001 — validation must never break planning
        return

    for slot, spec in (resolved or {}).items():
        values = [spec] if not isinstance(spec, dict) else list(spec.values())
        # A list value is a weekly-alternation set (e.g. ["Mutton Biryani",
        # "Fish Tikka Masala"]); validate each element, not the list object.
        flat: List[Any] = []
        for v in values:
            flat.extend(v) if isinstance(v, list) else flat.append(v)
        for value in flat:
            if value is None:
                continue
            if not isinstance(value, str):
                logger.warning(
                    "constant_items[%r] for %s is %s, not a string; it will "
                    "print as %r. Quote the value in client_rules.json.",
                    slot, client_name, type(value).__name__, str(value),
                )
                continue
            name = value.strip().lower()
            if name and name not in known and name.replace(' ', '_') not in known:
                logger.warning(
                    "constant_items[%r] for %s pins %r, which is not an item in "
                    "the ontology. It will be printed verbatim — check for a "
                    "typo, or confirm this is an intentional off-ontology dish.",
                    slot, client_name, value,
                )


def _resolve_constant_items(client_name, constant_items, client_cfg):
    """Resolve a client's raw ``constant_items`` block against ONE counter.

    Returns ``(resolved, whole_slot_bases)``. *resolved* maps a real slot id
    to its raw spec (daily string or weekday map); *whole_slot_bases* are base
    slots the overlay replaces outright, which the caller drops from the model
    rather than solving a cell whose value is immediately overwritten.

    Three things happen here, each a silent wrong-menu bug when skipped:

    * A slot this counter does not serve is dropped — ``constant_items`` is
      client-scoped but a client may have several counters, and a two-slot
      Chinese station should not grow a salad row. The exception is a slot
      whose mutually-exclusive sibling *is* served: ``curd``/``curd_side`` are
      one logical yogurt slot and pinning "curd Mon, raita Wed" across the
      pair is the entire point of the weekday-map form.
    * A key outside the slot registry is dropped with a warning instead of
      being stamped as an ad-hoc slot that has no display label and no rank
      in DISPLAY_SLOT_ORDER.
    * A bare base name on a multi-expansion slot resolves to the LAST
      expansion, so ``nonveg_main`` at count 2 keeps one solved dish and pins
      the other instead of losing both.
    """
    resolved: Dict[str, Any] = {}
    whole_slot_bases: Set[str] = set()
    if not constant_items:
        return resolved, whole_slot_bases

    # `_`-prefixed keys are documentation, the same convention the rules list
    # uses for `_comment`. Without this a comment inside a `constant_items`
    # block logs "not a known slot" on every single plan.
    constant_items = {
        k: v for k, v in constant_items.items() if not str(k).startswith('_')
    }

    known_slots = set(BASE_SLOT_NAMES) | set(CONST_SLOTS)
    active_slots = getattr(client_cfg, 'active_slots', None)

    if not active_slots:
        # No counter to resolve against (utility / direct callers). Keep the
        # registry check but leave keys untouched — dropping every constant
        # because a caller omitted client_cfg would be a silent data loss.
        for key, spec in constant_items.items():
            base = _base_slot(key)
            if base not in known_slots:
                logger.warning(
                    "Ignoring constant_items[%r]: %r is not a known slot.",
                    key, base,
                )
                continue
            resolved[key] = spec
            if isinstance(spec, str):
                whole_slot_bases.add(base)
        return resolved, whole_slot_bases

    served: Dict[str, List[str]] = {}
    for slot_id in active_slots:
        served.setdefault(_base_slot(slot_id), []).append(slot_id)

    for key, spec in constant_items.items():
        base = _base_slot(key)
        if base not in known_slots:
            logger.warning(
                "Ignoring constant_items[%r] for %s: %r is not a known slot. "
                "Valid slots are BASE_SLOT_NAMES + CONST_SLOTS.",
                key, client_name, base,
            )
            continue

        expansions = served.get(base, [])
        if not expansions:
            # No cell of its own. Legitimate only when a mutually-exclusive
            # sibling is served (the curd / curd_side pair); otherwise this
            # constant belongs to a different counter.
            if not (_exclusive_siblings(base) & set(served)):
                logger.debug(
                    "Dropping constant_items[%r] for %s: counter %r does not "
                    "serve %r.", key, client_name,
                    getattr(client_cfg, 'name', '?'), base,
                )
                continue
            resolved[base] = spec
            continue

        if key in expansions:
            target = key
        else:
            target = expansions[-1]
            if key != base:
                logger.warning(
                    "constant_items[%r] for %s: this counter has %d "
                    "expansion(s) of %r, pinning %r instead.",
                    key, client_name, len(expansions), base, target,
                )
        resolved[target] = spec
        # A daily string on a single-expansion slot replaces the slot for the
        # whole horizon, so there is nothing left worth solving.
        if len(expansions) == 1 and isinstance(spec, str):
            whole_slot_bases.add(base)

    return resolved, whole_slot_bases
