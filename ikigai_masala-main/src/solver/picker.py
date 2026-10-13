"""Put a named dish in a cell, without solving.

The planner has already decided. A pick is therefore not a search for a plan
that satisfies the rules — it is a statement that this dish goes in this cell,
and the rules it breaks are reported rather than enforced (decision D2). That
makes it the opposite of everything else in this package, so the shape is
deliberately different: stamp first, then audit what the stamp cost.

**It cannot be done by solving.** The obvious route — pin the dish and run
`/regenerate` — fails silently in exactly the way this repo keeps guarding
against: a pin naming a dish the pre-filters removed is logged at INFO and the
cell is "solved normally", so the planner would be served a different dish
than the one they typed, with a 200 and a plausible menu. `MenuSolver` has
that path for client constants and it is right there; it must not be reused
here (work order §2, contract §6.5).

Two things are NOT negotiable by a pick:

* **A pinned cell** (a global staple, a `forced_items` pin, a client
  constant) — decision D3. The table already refuses to select one; this is
  the same rule where it cannot be bypassed.
* **A dish twice in one ISO week** — decision D5, the one rule a pick cannot
  override. It is a 400, never a warning, and it runs BEFORE the cooldown
  audit: a dish served earlier this week is also inside the 21-day cooldown
  window, so checking cooldown first would report a blocking condition as a
  mere "served 3 days ago" and let it through.

Everything else that a pick breaks becomes an entry in `exceptions`, and what
could not be checked at all is named in `not_checked` — a list that is always
returned, because an Exceptions panel that looks complete and is not is worse
than one that admits its limits (note 9's shape, applied to a UI).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.constants import REPEATABLE_SLOTS
from src.preprocessor.column_mapper import _norm_str
from src.preprocessor.pool_builder import _base_slot
from ._helpers import strip_color_suffix
from .menu_solver import _fmt_item_with_color, pinned_cells_for_config

logger = logging.getLogger(__name__)

#: What the audit looks at, and what it cannot see. Returned verbatim on every
#: response. `not_checked` is the honest half: these rules exist only as CP-SAT
#: constraints inside a model nobody builds for a pick, so no amount of reading
#: the finished plan reveals them (work order §6.3).
CHECKED: Tuple[str, ...] = (
    'cooldown', 'client_pool', 'ricebread_gap', 'pre_filter_rules',
    'plate_checks',
)
NOT_CHECKED: Tuple[str, ...] = (
    'selector_frequency caps', 'slot_composition', 'colour constraints',
)


class PickError(Exception):
    """A pick the server refuses, with the planner-readable reason.

    Carries the contract's closed `code` and its `details` shape so the view
    does not have to map exceptions onto codes — the place that knows WHY a
    pick was refused is the place that refused it.
    """

    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _clean(value: Any) -> str:
    """An item as the ontology spells it: no colour suffix, no case, no space."""
    return _norm_str(strip_color_suffix(str(value or '')))


def _iso_week(d: dt.date) -> str:
    year, week, _ = d.isocalendar()
    return f'{year}-W{week:02d}'


def _city_slot_items(city_pools: Dict[str, Any], base: str) -> Dict[str, Any]:
    """``{normalised item: row}`` for one base slot of the CITY list.

    The city list, not the client's pool: decision D4. A dish the client's
    pool does not carry is still pickable and becomes a `client_pool` warning,
    because "this client doesn't normally serve it" is the planner's call to
    overrule, while "this city's kitchen has no such dish" is not.
    """
    pool = city_pools.get(base)
    if pool is None or not len(pool):
        return {}
    out = {}
    for row in pool.to_dict('records'):
        name = _clean(row.get('item'))
        if name:
            out.setdefault(name, row)
    return out


def week_items_in_plan(
    base_plan: Dict[dt.date, Dict[str, str]], week: str,
    *, skip: Set[Tuple[dt.date, str]] = frozenset(),
    pinned: Set[Tuple[dt.date, str]] = frozenset(),
) -> Dict[str, dt.date]:
    """``{item: the date it is on}`` for one ISO week of a plan.

    `skip` is the cells being picked (a cell does not repeat against itself).
    `pinned` and `REPEATABLE_SLOTS` are exempt, matching what the solver's own
    uniqueness constraint exempts: the daily curd is meant to recur, and a
    staple the client pinned to every day is not a repeat anyone chose.
    """
    out: Dict[str, dt.date] = {}
    for d, slots in (base_plan or {}).items():
        if _iso_week(d) != week:
            continue
        for slot_id, value in (slots or {}).items():
            if (d, slot_id) in skip or (d, slot_id) in pinned:
                continue
            if _base_slot(slot_id) in REPEATABLE_SLOTS:
                continue
            name = _clean(value)
            if name:
                out.setdefault(name, d)
    return out


def week_items_in_history(client_name: str, week_dates: List[dt.date]) -> Dict[str, dt.date]:
    """``{item: date}`` served by this client on *week_dates*, from saved plans.

    Decision D7: the same client, **all counters and all services**. Both fall
    out of reading `menu_history` rows directly — `explode_history_rows`
    flattens the nested per-counter shape, and the `meal` column is dropped on
    the way through (note 39, where that dropping IS the cross-service
    guarantee). Filtering either one here would quietly narrow D5 to one
    station's lunch.

    A database that cannot be reached is not allowed to turn a block into a
    silent pass: the caller gets the exception.
    """
    if not week_dates:
        return {}
    from src.db import get_supabase
    from src.history.history_manager import HistoryManager

    resp = (get_supabase().table('menu_history').select('*')
            .eq('client_name', client_name)
            .gte('service_date', min(week_dates).isoformat())
            .lte('service_date', max(week_dates).isoformat())
            .execute())
    long_df = HistoryManager.explode_history_rows(resp.data)
    out: Dict[str, dt.date] = {}
    if long_df is None or not len(long_df):
        return out
    for row in long_df.to_dict('records'):
        if _base_slot(str(row.get('slot') or '')) in REPEATABLE_SLOTS:
            continue
        name = _clean(row.get('item_base'))
        if not name:
            continue
        try:
            served = dt.date.fromisoformat(str(row.get('service_date'))[:10])
        except (TypeError, ValueError):
            continue
        out.setdefault(name, served)
    return out


def apply_picks(inputs, base_plan: Dict[dt.date, Dict[str, str]],
                picks: Dict[dt.date, Dict[str, str]],
                *, city_pools: Dict[str, Any],
                history_lookup=week_items_in_history) -> Dict[str, Any]:
    """Validate every pick, then stamp them all. All or nothing.

    Atomic because a partial application is unreportable: the planner asked
    for N cells and would get back a plan with some of them changed and no
    way to tell which, or why the rest were not. Every check below therefore
    runs over the whole request before anything is written.

    Returns ``{week_plan, manual_cells, changed}``. The audit is the caller's
    next step; `exceptions` is filled in Phase 3.
    """
    planned = set(inputs.weekday_dates or [])
    pinned = pinned_cells_for_config(inputs.cfg, inputs.skip_cells)
    targets: List[Tuple[dt.date, str, str, Any]] = []
    cells = {(d, s) for d, slots in picks.items() for s in slots}

    for d in sorted(picks):
        for slot_id, raw in sorted(picks[d].items()):
            iso = d.isoformat()
            if d not in planned:
                raise PickError(
                    'bad_date',
                    f'{iso} is not one of this plan\'s days. Reload the plan '
                    f'and try again.', {'date': iso})
            if slot_id not in (base_plan.get(d) or {}):
                raise PickError(
                    'unknown_cell',
                    f'There is no {slot_id} cell on {iso} in this plan.',
                    {'date': iso, 'slot_id': slot_id})
            if (d, slot_id) in pinned:
                raise PickError(
                    'pinned_cell',
                    "That cell is pinned by a client rule. Search and "
                    "Regenerate can't change it.",
                    {'date': iso, 'slot_id': slot_id})

            base = _base_slot(slot_id)
            item = _clean(raw)
            row = _city_slot_items(city_pools, base).get(item)
            if row is None:
                raise PickError(
                    'not_a_slot_dish',
                    f'{raw} is not a {base.replace("_", " ")} dish in the '
                    f'{inputs.city} list.',
                    {'item': item, 'slot_id': slot_id, 'city': inputs.city})
            targets.append((d, slot_id, item, row))

    _reject_week_repeats(inputs, base_plan, targets, cells, pinned,
                         history_lookup)

    week_plan = {d: dict(slots) for d, slots in base_plan.items()}
    manual: Dict[str, List[str]] = {}
    changed = False
    for d, slot_id, item, row in targets:
        # The solver's own formatting, not a reconstruction of it: the colour
        # suffix is part of the stored spelling, and a plan saved with a
        # different one matches no pool row on the way back — never banned,
        # never aged, and no log line about it (note 28).
        stamped = _fmt_item_with_color(row, inputs.cfg.color_col)
        if _clean(week_plan.get(d, {}).get(slot_id)) != item:
            changed = True
        week_plan.setdefault(d, {})[slot_id] = stamped
        manual.setdefault(d.isoformat(), []).append(slot_id)
    return {'week_plan': week_plan, 'manual_cells': manual, 'changed': changed}


def _reject_week_repeats(inputs, base_plan, targets, cells, pinned,
                         history_lookup) -> None:
    """Decision D5, over three sources: the plan, this request, saved history.

    Checked per ISO week rather than per plan because a horizon can span two
    of them — `/plan` accepts up to `MAX_NUM_DAYS`, and a week that starts on
    a Thursday is two ISO weeks, where "twice in a week" means twice in one of
    them, not twice in the fortnight.
    """
    by_week: Dict[str, List] = {}
    for target in targets:
        by_week.setdefault(_iso_week(target[0]), []).append(target)

    for week, group in sorted(by_week.items()):
        in_plan = week_items_in_plan(base_plan, week, skip=cells, pinned=pinned)
        week_dates = sorted(d for d in (inputs.weekday_dates or [])
                            if _iso_week(d) == week)
        in_history = history_lookup(inputs.client_name, week_dates)
        seen_here: Dict[str, dt.date] = {}
        for d, slot_id, item, _row in group:
            if _base_slot(slot_id) in REPEATABLE_SLOTS:
                continue
            for source, where in (('plan', in_plan.get(item)),
                                  ('pick', seen_here.get(item)),
                                  ('history', in_history.get(item))):
                if where is None:
                    continue
                raise PickError('week_repeat', _repeat_message(item, where, source),
                                {'item': item, 'on': where.isoformat(),
                                 'week': week, 'source': source})
            seen_here[item] = d


def _repeat_message(item: str, where: dt.date, source: str) -> str:
    pretty = item.replace('_', ' ').capitalize()
    day = where.strftime('%a %-d %b')
    if source == 'history':
        return (f'{pretty} was already served on {day} this week. '
                f"A dish can't repeat in a week.")
    if source == 'pick':
        return (f'{pretty} is already one of the dishes you are placing this '
                f"week ({day}). A dish can't repeat in a week.")
    return f"{pretty} is already on {day}. A dish can't repeat in a week."
