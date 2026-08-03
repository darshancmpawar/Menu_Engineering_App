"""
Unique items menu rule: each item at most once per planning session.

Uses item_to_vars from context (built by solver) to enforce uniqueness.
"""

import logging
import math
from typing import Any, Dict, List, Set, Tuple

from ortools.sat.python import cp_model
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from src.constants import (
    OBJECTIVE_TIER_WEIGHTS,
    REPEATABLE_SLOTS,
    repeatable_row,
)
from ..preprocessor.column_mapper import _norm_str

logger = logging.getLogger(__name__)


def matches_declared(row, base_slot, declared) -> bool:
    """True when *row* is covered by a rule-declared repeatable selector.

    ``declared`` is ``{base_slot: [(include, exclude), ...]}`` as collected from
    every rule exposing ``repeatable_item_flags()`` — see FixedDailyItemRule and
    RepeatableItemsRule. Scoped per city/client, unlike the ontology-wide
    REPEATABLE_ITEM_FLAGS_BY_SLOT.

    Public because the item-cooldown pre-filter reads the same declarations: a
    staple exempted from unique_items but still banned by history is not a
    staple, it is a slot that starves one week later.
    """
    from .selector_frequency_rule import SelectorFrequencyRule
    for include, exclude in (declared or {}).get(base_slot, ()):
        if (SelectorFrequencyRule._matches(row, include)
                and not SelectorFrequencyRule._matches(row, exclude)):
            return True
    return False


def starved_slots(cells, declared=None) -> Dict[str, int]:
    """Return ``{base_slot: max_repeats}`` for slots that cannot be unique.

    A slot is *starved* when the number of distinct items across its cells'
    candidate pools is smaller than the number of cells that need filling —
    e.g. ``curd_rice`` has 4 eligible items but a 5-day plan needs 5 distinct
    ones. Strict uniqueness is then arithmetically impossible and the whole
    model is INFEASIBLE, which surfaced to users as a bare "No feasible plan
    found after CP-SAT restarts" with no indication of which slot was at fault.

    ``max_repeats`` is reported for diagnostics — ``ceil(cells / distinct)`` is
    the average number of uses each item would need — but ``apply()`` does not
    impose it as a cap. A tighter-than-necessary cap is not provably safe: on
    L&T's south-only counter three raita/curd candidates cover five days on
    average, yet ``curd_side_menu_rule`` separately forces the single
    ``sub_category == 'curd'`` item on every non-pulao day, so a cap of 2 is
    still INFEASIBLE. Uniqueness is therefore dropped outright for a starved
    slot and the accompanying diagnostic says so.

    Slots in ``REPEATABLE_SLOTS`` are excluded — they are exempt from
    uniqueness by design and the solver never tracks their vars.
    """
    stats: Dict[str, Dict[str, Any]] = {}
    for cell in cells:
        if cell.base_slot in REPEATABLE_SLOTS:
            continue
        entry = stats.setdefault(
            cell.base_slot, {'cells': 0, 'items': set(), 'staple': False})
        entry['cells'] += 1
        for row in cell.cand_rows:
            if (repeatable_row(row, cell.base_slot)
                    or matches_declared(row, cell.base_slot, declared)):
                # A staple can cover any number of cells on its own, so its
                # presence means this slot can never be arithmetically starved.
                entry['staple'] = True
                continue
            entry['items'].add(_norm_str(row.get('item', '')))

    out: Dict[str, int] = {}
    for slot, entry in stats.items():
        if entry['staple']:
            continue
        distinct = len({i for i in entry['items'] if i})
        if distinct and distinct < entry['cells']:
            out[slot] = max(1, math.ceil(entry['cells'] / distinct))
    return out


class UniqueItemsMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "unique_items",
        "name": "unique_items_session",
        "scope": "session"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.UNIQUE_ITEMS
        self.scope = rule_config.get('scope', 'session').lower()

    def validate_config(self) -> bool:
        return self.scope in ('session',)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        item_to_vars = context.get('item_to_vars', {})
        if not item_to_vars:
            return
        declared = context.get('extra_repeatable') or {}
        repeatable = {
            _norm_str(row.get('item', ''))
            for cell in cells for row in cell.cand_rows
            if (repeatable_row(row, cell.base_slot)
                or matches_declared(row, cell.base_slot, declared))
        }
        repeatable.discard('')

        self._repeat_penalty_vars = []
        relaxed = starved_slots(cells, declared) if cells else {}
        if not relaxed:
            # Fast path — identical to the original global constraint.
            for item_base, vars_ in item_to_vars.items():
                if item_base not in repeatable:
                    model.Add(sum(vars_) <= 1)
            return

        for slot, avg in sorted(relaxed.items()):
            logger.warning(
                "unique_items: slot %r has fewer distinct eligible items than "
                "cells to fill (each item would be needed ~%d time(s)); "
                "dropping uniqueness for this slot instead of failing the whole "
                "plan, so items in it may repeat. Add items to this slot, widen "
                "the client's source_pools, or reduce its slot count / horizon.",
                slot, avg,
            )

        # Uniqueness still holds everywhere else. Occurrences of an item inside
        # a starved slot are simply left unconstrained; occurrences of the same
        # item in any healthy slot keep the strict "once per horizon" rule.
        healthy: Dict[str, List[Any]] = {}
        for cell in cells:
            if cell.base_slot in REPEATABLE_SLOTS or cell.base_slot in relaxed:
                continue
            for var, row in zip(cell.x_vars, cell.cand_rows):
                item_base = _norm_str(row.get('item', ''))
                if item_base in repeatable:
                    continue
                healthy.setdefault(item_base, []).append(var)

        for item_base, vars_ in healthy.items():
            model.Add(sum(vars_) <= 1)

        # Relaxed does not mean unconstrained. A slot with 4 items over 5 days
        # must repeat exactly once — serving one dish five times satisfies the
        # same lifted constraint but is not the menu anyone wants. Record a
        # per-item "used more than once" bool so get_objective_terms can charge
        # for each repeat, which drives the solver to spread across the whole
        # pool and repeat the minimum number of times.
        self._repeat_penalty_vars = []
        for slot in relaxed:
            slot_cells = [c for c in cells if c.base_slot == slot]
            by_item: Dict[str, List[Any]] = {}
            for c in slot_cells:
                for var, row in zip(c.x_vars, c.cand_rows):
                    item_base = _norm_str(row.get('item', ''))
                    if item_base and item_base not in repeatable:
                        by_item.setdefault(item_base, []).append(var)
            for item_base, vars_ in by_item.items():
                if len(vars_) < 2:
                    continue
                extra = model.NewIntVar(
                    0, len(vars_), f'repeat_{slot}_{item_base}'[:190])
                # extra >= uses - 1  ->  every use beyond the first is charged
                model.Add(extra >= sum(vars_) - 1)
                self._repeat_penalty_vars.append(extra)

    def get_objective_terms(self, model: cp_model.CpModel,
                            context: Dict[str, Any]) -> List:
        """Charge for every avoidable repeat inside a relaxed slot.

        Weighted at the HIGH tier so variety outranks ordinary soft preferences
        but never competes with theme adherence — the menu should look as varied
        as the pool allows without reordering the cuisine logic above it.
        """
        penalties = getattr(self, '_repeat_penalty_vars', None) or []
        weight = OBJECTIVE_TIER_WEIGHTS['high']
        return [-weight * v for v in penalties]

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Warn when a slot's eligible pool is too small to stay unique.

        The binding constraint for a small pool is *horizon* uniqueness —
        one distinct item per cell across the whole plan — not the per-day
        pool size that ``pool_size_diagnostics`` checks. A slot with 4
        eligible items in a 5-day plan passes every per-day check and then
        fails the solve, so this is reported here instead.

        Severity is WARNING, not ERROR: ``apply()`` relaxes the cap rather
        than failing, so the plan is still produced — the user just needs to
        know an item will repeat and why.
        """
        diags: List[Diagnostic] = []
        base_slots = ctx.active_base_slots
        if base_slots is None:
            return diags
        slot_counts = ctx.client_cfg.slot_counts if ctx.client_cfg is not None else {}
        skip: Set[Tuple[Any, str]] = ctx.skip_cells or set()
        # Slots whose staples a peer rule declared (repeatable_items,
        # fixed_daily_item). "Items will repeat" is what those rules were added
        # to do, so reporting it as a shortfall is noise that buries the real
        # warnings — Amadeus Pune's chapati-daily bread and buttermilk-daily
        # welcome drink each produced one every single plan.
        declared = self._declared_repeatable()

        for base in base_slots:
            if base in REPEATABLE_SLOTS or base not in ctx.pools:
                continue
            per_day = int(slot_counts.get(base, 1)) if slot_counts else 1
            if per_day <= 0:
                continue

            needed = 0
            available: Set[str] = set()
            for d in ctx.dates:
                if (d, base) in skip:
                    continue
                pool = ctx.pools[base]
                if base in ('rice', 'healthy_rice') and len(pool) > 0:
                    pool = pool[~pool['item'].isin(ctx.cfg.rice_exclude_items)]
                day_type = ctx.day_types.get(d, '')
                filter_ctx = {
                    'cfg': ctx.cfg, 'banned_by_date': {},
                    'ricebread_ban_day': {}, 'pools': ctx.pools,
                    'slot_num': None,
                }
                for rule in (self._peer_rules or []):
                    pool = rule.pre_filter_pool(pool, d, base, day_type, filter_ctx)
                needed += per_day
                if len(pool):
                    available.update(
                        _norm_str(v) for v in pool['item'].tolist()
                    )
                    if any(
                        repeatable_row(row, base)
                        or matches_declared(row, base, declared)
                        for _i, row in pool.iterrows()
                    ):
                        # A staple can cover any number of cells on its own, so
                        # this slot can never run short. Same predicate apply()
                        # uses, so the report and the solve agree.
                        needed = 0
                        break

            distinct = len({i for i in available if i})
            if needed and distinct and distinct < needed:
                diags.append(Diagnostic(
                    rule=self.name,
                    rule_type=self.rule_type.value,
                    severity=DiagnosticSeverity.WARNING,
                    phase=DiagnosticPhase.APPLY,
                    message=(
                        f"Slot '{base.replace('_', ' ')}' has only {distinct} "
                        f"distinct eligible item(s) but the plan needs {needed} "
                        f"across the horizon; item(s) will repeat."
                    ),
                    suggestion=(
                        f"Add more {base.replace('_', ' ')} items to this "
                        f"client's item pools (source_pools), shorten the "
                        f"horizon, or reduce the slot count."
                    ),
                    affected={
                        'base_slot': base,
                        'distinct_available': distinct,
                        'cells_needed': needed,
                    },
                ))
        return diags

    # Set by the diagnostics aggregator so diagnose() can replay the
    # pre-filter chain (theme filters shrink the eligible pool, and that
    # shrinkage is exactly what starves a slot — see L&T's south-only
    # counter, where curd_side drops from 13 items to 3).
    _peer_rules: List[Any] = []

    def _declared_repeatable(self) -> Dict[str, List[Any]]:
        """``{base_slot: [(include, exclude), ...]}`` from every peer rule.

        The same collection ``MenuSolver._declared_repeatable()`` hands ``apply()``
        via ``context['extra_repeatable']``; diagnose() has no context, so it
        reads the peers directly.
        """
        out: Dict[str, List[Any]] = {}
        for rule in (self._peer_rules or ()):
            fn = getattr(rule, 'repeatable_item_flags', None)
            if not callable(fn):
                continue
            try:
                for slot, matcher in (fn() or {}).items():
                    out.setdefault(slot, []).append(matcher)
            except Exception:  # noqa: BLE001 — a bad peer must not break diagnose
                continue
        return out
