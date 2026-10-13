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

from src.constants import DEFAULT_ITEM_COOLDOWN_DAYS, REPEATABLE_SLOTS
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

    **`week_dates` must exclude the dates of the plan being edited.** The plan
    on screen may already have been saved — `/save` writes per (client, date)
    and the planner may well have saved before picking — and those rows hold
    the very dishes now on screen. Counting them would make every dish on a
    saved plan block itself, and the planner would see "already served on
    Tuesday" for the dish sitting in Tuesday's cell. The caller does the
    exclusion, because only it knows the horizon.

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
    return {'week_plan': week_plan, 'manual_cells': manual,
            'changed': changed, 'targets': targets}


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
        # The week's days that are NOT in this plan. A saved copy of the plan
        # on screen would otherwise block every dish against itself — see
        # `week_items_in_history`. A Wednesday-start plan still sees the
        # Monday and Tuesday that were saved before it.
        horizon = set(inputs.weekday_dates or []) | set(base_plan or {})
        week_dates = sorted(_week_days(week) - horizon)
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


def _week_days(week: str) -> Set[dt.date]:
    """The seven dates of an ISO week string (`2026-W45`)."""
    year, num = week.split('-W')
    monday = dt.date.fromisocalendar(int(year), int(num), 1)
    return {monday + dt.timedelta(days=i) for i in range(7)}


def _repeat_message(item: str, where: dt.date, source: str) -> str:
    """Spec 04 §3.5, verbatim: what happened, then why it is refused."""
    pretty = item.replace('_', ' ').capitalize()
    day = where.strftime('%a %-d %b')
    if source == 'history':
        return (f'{pretty} was served on {day} in a saved plan. '
                f"A dish can't repeat in a week.")
    if source == 'pick':
        return (f'You picked {pretty} twice in one request. '
                f"A dish can't repeat in a week.")
    return f"{pretty} is already on {day}. A dish can't repeat in a week."


# ---------------------------------------------------------------------------
# The audit: what the pick cost, reported rather than enforced (decision D2)
# ---------------------------------------------------------------------------


def _violation(code: str, rule: str, message: str, details=None) -> Dict[str, Any]:
    """Every finding is a `warning` in v1.

    The field exists so a later version can add a level without a contract
    change, and it is deliberately NOT used to sneak a block in: a pick that
    reaches the audit has already passed every guard, and D2 says the planner
    decides from here.
    """
    return {'code': code, 'rule': rule, 'severity': 'warning',
            'message': message, 'details': details or {}}


def _filter_context(inputs, solver) -> Dict[str, Any]:
    """The context `pre_filter_pool` is called with during a real solve.

    Borrowed from a `MenuSolver` rather than rebuilt: `_build_day_base_pool_cache`
    assembles exactly these keys, and the two rule-declaration hooks behind
    `extra_repeatable` / `extra_cooldown_exempt` walk the loaded rules. A
    second copy here would be a context that drifts from the one the rules
    were written against, and the probe would then answer about a solve that
    never happens. Constructing a `MenuSolver` is free — `__init__` is
    assignment only, and nothing solves until `solve()` is called.
    """
    return {
        'cfg': inputs.cfg,
        'banned_by_date': inputs.banned,
        'ricebread_ban_day': inputs.rb_ban,
        'pools': inputs.pools,
        'extra_repeatable': solver._repeatable_declarations(),
        'extra_cooldown_exempt': solver._declared_repeatable(
            'cooldown_exempt_item_flags'),
        'slot_num': None,
    }


def _cooldown_violation(inputs, d: dt.date, item: str) -> Optional[Dict[str, Any]]:
    banned = {_clean(x) for x in (inputs.banned or {}).get(d, set())}
    if item not in banned:
        return None
    days_ago = (inputs.recency_by_item or {}).get(item)
    window = getattr(inputs.cfg, 'item_cooldown_days', None) or DEFAULT_ITEM_COOLDOWN_DAYS
    if days_ago is None:
        message = (f'Served recently. This client serves a dish at most once '
                   f'every {window} days.')
        details = {'window_days': window}
    else:
        last = d - dt.timedelta(days=int(days_ago))
        message = (f'Served {int(days_ago)} days ago '
                   f'({last.strftime("%a %-d %b")}). '
                   f"This client's window is {window} days.")
        details = {'last_served': last.isoformat(), 'days_ago': int(days_ago),
                   'window_days': window}
    return _violation('cooldown', 'item_cooldown', message, details)


def _client_pool_violation(inputs, base: str, item: str) -> Optional[Dict[str, Any]]:
    pool = (inputs.pools or {}).get(base)
    if pool is None or not len(pool):
        return None
    if item in {_clean(v) for v in pool['item'].tolist()}:
        return None
    return _violation(
        'client_pool', 'client_pool',
        f'On the {inputs.city} city list, but not in '
        f"{inputs.client_name}'s dish pool.",
        {'base_slot': base})


def _ricebread_violation(inputs, d: dt.date, base: str) -> Optional[Dict[str, Any]]:
    if base != 'bread' or not (inputs.rb_ban or {}).get(d):
        return None
    return _violation(
        'ricebread_gap', 'ricebread_gap',
        f"Bread isn't allowed on {d.strftime('%a %-d %b')}: the rice-bread "
        f'gap rule.')


def _rule_violations(inputs, d: dt.date, base: str, row, ctx, day_type: str,
                     covered: bool = False):
    """Ask each rule's own pre-filter whether it would have removed this dish.

    A one-row frame through the real hook, not a reimplementation of what each
    rule means: there are ~70 of them and a second reading of any one would be
    a rule the Exceptions panel describes wrongly. If the row comes back
    removed, that rule would have kept this dish out of the cell.

    A rule that RAISES is named in `errored` and reported under `not_checked`,
    never swallowed and never fatal. Losing a constraint silently is the thing
    this whole feature is most exposed to; an audit that quietly drops a rule
    looks exactly like one that found nothing.
    """
    import pandas as pd

    out, errored = [], []
    one_row = pd.DataFrame([row])
    for rule in (inputs.rules or []):
        name = getattr(rule, 'name', '') or type(rule).__name__
        fn = getattr(rule, 'pre_filter_pool', None)
        if not callable(fn):
            continue
        try:
            kept = fn(one_row, d, base, day_type, ctx)
        except Exception as exc:                            # noqa: BLE001
            logger.warning('pick audit: rule %r pre_filter_pool raised: %s',
                           name, exc)
            errored.append(f'rule:{name} (errored)')
            continue
        if kept is None or len(kept):
            continue
        if covered and _removal_is_already_reported(fn, one_row, d, base,
                                                    day_type, ctx):
            continue
        detail = ''
        describe = getattr(rule, 'get_description', None)
        if callable(describe):
            try:
                detail = str(describe() or '')
            except Exception:                               # noqa: BLE001
                detail = ''
        out.append(_violation(
            f'rule:{name}', name,
            detail or f'The rule {name} would have kept this dish out of '
                      f'this cell.'))
    return out, errored


def _removal_is_already_reported(fn, one_row, d, base, day_type, ctx) -> bool:
    """Did this rule drop the row only because of a fact already reported?

    The item cooldown and the rice-bread gap each have a named code above AND
    a rule in the loaded set, so their pre-filters restate the same finding
    under `rule:<name>` — the planner would read "served 5 days ago" twice in
    different words. Spec §5.1: report each violated thing once, preferring
    the specific code.

    Decided by RE-PROBING with those two inputs cleared for the day rather
    than by a list of rule class names. A name list goes stale the first time
    a client ships its own cooldown rule under another name, and goes stale
    silently — the duplicate just comes back. This asks the rule itself: if
    the row survives once the ban maps are empty, the ban is the whole reason
    it was removed and is already in the response.
    """
    probe = dict(ctx)
    probe['banned_by_date'] = {**(ctx.get('banned_by_date') or {}), d: set()}
    probe['ricebread_ban_day'] = {**(ctx.get('ricebread_ban_day') or {}), d: False}
    try:
        kept = fn(one_row, d, base, day_type, probe)
    except Exception:                                       # noqa: BLE001
        return False
    return kept is not None and len(kept) > 0


def _plate_violations(inputs, before_day, after_day) -> List[Dict[str, Any]]:
    """Checks that PASSED before the pick and fail after it.

    Only the difference, per spec §1.6: a plate that was already short on
    colour is not the pick's doing, and blaming it would bury the one finding
    that is. `run_checks` never raises (it skips a check that does), so a
    broken check costs this audit a line, not the request.
    """
    from src.explain.checks import run_checks
    from src.explain.evidence import attrs_from_dataframe, build_dishes

    attrs = attrs_from_dataframe(inputs.df)
    was = {c.name: c for c in run_checks(build_dishes(before_day, attrs))}
    now = {c.name: c for c in run_checks(build_dishes(after_day, attrs))}
    out = []
    for name, check in now.items():
        prior = was.get(name)
        if prior is None or not getattr(prior, 'passed', True):
            continue
        if getattr(check, 'passed', True):
            continue
        out.append(_violation(
            f'plate:{name}', name,
            str(getattr(check, 'detail', '') or
                f'{name} passed before this pick and does not now.')))
    return out


def audit_picks(inputs, before_plan, after_plan, targets) -> Tuple[List[Dict], List[str]]:
    """One `exceptions` entry per pick that broke something, plus extra gaps.

    Returns `(exceptions, extra_not_checked)`. A clean pick produces no entry
    at all, so an empty list means "nothing we can see", which is why the
    second half of the pair matters as much as the first.
    """
    from .menu_solver import MenuSolver
    from ._helpers import weekday_type_for_config

    solver = MenuSolver(
        inputs.pools, inputs.cfg, menu_rules=inputs.rules,
        banned_by_date=inputs.banned, ricebread_ban_day=inputs.rb_ban,
        skip_cells=inputs.skip_cells, recency_by_item=inputs.recency_by_item)
    ctx = _filter_context(inputs, solver)

    exceptions: List[Dict[str, Any]] = []
    errored: List[str] = []
    for d, slot_id, item, row in targets:
        base = _base_slot(slot_id)
        day_type = weekday_type_for_config(d, inputs.cfg.theme_map)
        found = [v for v in (
            _cooldown_violation(inputs, d, item),
            _client_pool_violation(inputs, base, item),
            _ricebread_violation(inputs, d, base),
        ) if v]
        rule_hits, rule_errors = _rule_violations(
            inputs, d, base, row, ctx, day_type, covered=bool(found))
        errored.extend(rule_errors)
        found.extend(rule_hits)
        found.extend(_plate_violations(
            inputs, before_plan.get(d, {}), after_plan.get(d, {})))
        if found:
            exceptions.append({
                'date': d.isoformat(), 'slot_id': slot_id, 'item': item,
                'replaced': _clean(before_plan.get(d, {}).get(slot_id)),
                'violations': found,
            })
    return exceptions, sorted(set(errored))
