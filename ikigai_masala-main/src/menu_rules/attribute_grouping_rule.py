"""Generic attribute-grouping frequency rule (Phase-3 rule-type framework).

Where ``selector_frequency`` counts a *fixed* set of matching items, this rule
groups a slot's candidates by the *value* of some attribute column and
constrains each distinct value independently. It covers the rulebook's
"same X can't repeat" constraints without one class per attribute:

  * Rule 79 — the same dal colour cannot appear on two consecutive dal days
    (``group_by: item_color``, ``non_consecutive: true``).
  * Rule 82 — the same sambar key ingredient cannot repeat within the window
    (``group_by: key_ingredient``, ``max_per_group: 1``). With an empty
    history the 15-day rolling window collapses to the planning horizon, so a
    per-group horizon cap models it until menu history accumulates.
  * "the key ingredient must not come back for three days, and a week should
    carry as many different ones as it can" — ``min_days_between: 3`` with
    ``per_base_slot`` and ``require_value``. The soft half of that sentence is
    ``soft_preference``'s ``avoid_attribute_repeat`` at ``scope: week``/``day``.

Config::

    {
        "type": "attribute_grouping",
        "name": "dal_colour_non_consecutive",
        "base_slot": "dal",           # slot to scope to (required in practice)
        "group_by": "item_color",     # attribute column defining the groups
        "non_consecutive": true,      # same value may not be on adjacent days
        "min_days_between": null,     # ... or N CLEAR days between repeats
        "per_base_slot": false,       # constrain each slot on its own
        "require_value": false,       # a blank value is not eligible at all
        "max_per_group": null         # each value appears on <= N days / horizon
    }

At least one of ``non_consecutive`` / ``min_days_between`` / ``max_per_group``
must be set. All are caps — they never *force* a value to appear — so the rule
can only tighten a model, never make it infeasible on its own (a same-value ban
can still bite if a day's pool collapses to one value, which the pre-flight
diagnostics are there to surface).

Three keys exist for the key-ingredient rule and each earns its place:

``min_days_between`` is ``non_consecutive`` with the gap named. ``non_consecutive``
is exactly ``min_days_between: 1`` — one clear day — and is kept because sixty
configs say it.

``per_base_slot`` constrains **each slot independently** instead of pooling the
day's cells. Plate-wide is the reading that sounds right and cannot be built:
``nonveg_main`` carries six distinct key ingredients across the whole ontology
and ``nonveg_main_daily_pair`` mandates a chicken gravy every day, so one
plate-wide ban on ``chicken`` makes all 59 non-veg counters INFEASIBLE on day
two. Per slot, every pool except ``nonveg_main``/``healthy_rice``/``starter``
clears a four-day window on every counter. The same-day echo across slots —
carrot in the gravy AND the salad — is a *soft* penalty, where being outbid is
the correct outcome.

``require_value`` drops a candidate whose ``group_by`` cell is blank. Without it
the rule is worse than nothing: ``apply`` skips empty values (a blank row is
unconstrained), so the solver escapes the constraint by serving exactly the
dishes nobody has classified — and ``key_ingredient`` is blank on 36% of the
Bangalore workbook and 40% of some client starter pools. The drop **stands down
for any slot it would starve** (Booking.com's ``nonveg_soup`` and
``infused_water`` are 100% blank, so the filter would empty them outright), which
is the note-9c pattern: degrade provably, and say so.
"""

import datetime as dt
import logging
from collections import defaultdict
from typing import Dict, Any, List, Optional

import pandas as pd
from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from ..constants import CONST_SLOTS, REPEATABLE_SLOTS, repeatable_row
from ..preprocessor.column_mapper import _norm_cell, _norm_str
from .relaxations import RELAXATION

logger = logging.getLogger(__name__)


def _norm_slots(bs):
    """Normalise a ``base_slot``-ish config value to a set of names, or None.

    Same helper as ``soft_preference``'s, and for the same reason: a LIST that
    falls through to a ``!=`` against a string is always true, so the rule
    matches nothing and goes silently inert.
    """
    if isinstance(bs, (list, tuple, set, frozenset)):
        out = {str(x) for x in bs if str(x).strip()}
        return out or None
    return {str(bs)} if bs else None


def _has_value(col: 'pd.Series') -> 'pd.Series':
    """Boolean mask of cells that actually carry a value.

    ``col.astype(str)`` is NOT enough: under pandas' ``str`` dtype a NaN stays
    NaN rather than becoming the string ``'nan'``, so a ``!= ''`` test reports
    an empty column as fully populated. That artefact is why ``key_ingredient``
    was measured at 0% blank when it is blank on a third of the rows.
    """
    return ~(col.isna() | (col.fillna('').astype(str).str.strip() == ''))


class AttributeGroupingRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.ATTRIBUTE_GROUPING
        bs = rule_config.get('base_slot')
        # `base_slot` accepts a name or a LIST, matching selector_frequency and
        # soft_preference. "the veg plate" is veg_gravy AND veg_dry together —
        # scoping it to either one is a different rule and misses the echo that
        # spans them. `self.base_slot` keeps the string form so diagnose() and
        # every existing single-slot config behave exactly as before.
        self.base_slots: Optional[set] = _norm_slots(bs)
        self.base_slot: Optional[str] = None if isinstance(
            bs, (list, tuple, set, frozenset)) else bs
        self.group_by: str = str(rule_config.get('group_by') or '')
        self.non_consecutive: bool = bool(rule_config.get('non_consecutive', False))
        mdb = rule_config.get('min_days_between')
        self.min_days_between: Optional[int] = int(mdb) if mdb is not None else None
        self.per_base_slot: bool = bool(rule_config.get('per_base_slot', False))
        self.require_value: bool = bool(rule_config.get('require_value', False))
        mpg = rule_config.get('max_per_group')
        self.max_per_group: Optional[int] = int(mpg) if mpg is not None else None
        mcd = rule_config.get('max_cells_per_day')
        self.max_cells_per_day: Optional[int] = int(mcd) if mcd is not None else None

    @property
    def _gap(self) -> int:
        """Clear days that must separate two uses of one value.

        ``non_consecutive`` is the same constraint with the gap left implicit,
        so the two collapse to one number here and the window below is
        ``gap + 1`` days wide either way.
        """
        if self.min_days_between is not None:
            return self.min_days_between
        return 1 if self.non_consecutive else 0

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.group_by:
            errs.append("group_by (an attribute column name) is required")
        if (not self.non_consecutive and self.max_per_group is None
                and self.min_days_between is None
                and self.max_cells_per_day is None):
            errs.append("at least one of non_consecutive / min_days_between / "
                        "max_per_group / max_cells_per_day is required")
        if self.max_per_group is not None and self.max_per_group < 0:
            errs.append(f"max_per_group must be >= 0 (got {self.max_per_group})")
        if self.min_days_between is not None and self.min_days_between < 1:
            errs.append("min_days_between must be >= 1 (got "
                        f"{self.min_days_between}); 0 would constrain nothing")
        if self.max_cells_per_day is not None and self.max_cells_per_day < 1:
            errs.append("max_cells_per_day must be >= 1 (got "
                        f"{self.max_cells_per_day}); 0 would forbid the slot "
                        "outright, which is selector_frequency's job")
        return errs

    # ----- Phase 1: a candidate with no value is not a candidate -----

    def pre_filter_pool(self, pool: 'pd.DataFrame', date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> 'pd.DataFrame':
        """Drop candidates whose ``group_by`` cell is blank, when asked to.

        Standing down rather than starving: a slot left with fewer distinct
        dishes than the horizon has days cannot fill itself, and an empty pool
        is an outright INFEASIBLE. In both cases the drop is abandoned for that
        slot and reported — the rule is a variety preference, and no variety
        preference is worth a plan.

        Staples are never dropped. A dish declared repeatable is on the menu by
        a rule's explicit instruction (Pune's plain chapati, the daily curd),
        and whether anyone has typed its key ingredient is beside the point.
        """
        if not self.require_value or not self.group_by:
            return pool
        if self.base_slots is not None and base_slot not in self.base_slots:
            return pool
        if base_slot in CONST_SLOTS or base_slot in REPEATABLE_SLOTS:
            return pool
        if pool is None or len(pool) == 0 or self.group_by not in pool.columns:
            return pool

        has_value = _has_value(pool[self.group_by])
        if bool(has_value.all()):
            return pool

        # Only the rows that would actually be dropped are asked the (row-wise,
        # therefore slow) staple question — on a full pool that is the whole
        # frame, and this runs once per date per slot.
        from .unique_items_menu_rule import matches_declared
        declared = filter_context.get('extra_repeatable') or {}
        blanks = pool[~has_value]
        staple = blanks.apply(
            lambda row: (repeatable_row(row, base_slot)
                         or matches_declared(row, base_slot, declared)),
            axis=1,
        )
        keep = has_value.copy()
        if len(blanks):
            keep.loc[blanks.index] = staple.astype(bool)
        kept = pool[keep]
        if len(kept) == len(pool):
            return pool

        cfg = filter_context.get('cfg')
        per_day = 1
        days = 1
        if cfg is not None:
            per_day = int((getattr(cfg, 'slot_counts', None) or {}).get(base_slot, 1) or 1)
            days = int(getattr(cfg, 'days', 1) or 1)
        needed = max(per_day, days * per_day)
        if len(kept) < needed:
            logger.info(
                "%s: dropping blank-%s candidates would leave %s only %d "
                "dish(es) against %d needed, so every candidate is kept for "
                "that slot and the variety rule does not govern it",
                self.name, self.group_by, base_slot, len(kept), needed,
                extra={RELAXATION: self.name},
            )
            return pool
        return kept

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')
        if not cells or not link_any or not self.group_by:
            return
        declared = context.get('extra_repeatable') or {}
        # `si` is the scope's position in a SORTED list, never hash(name):
        # string hashing is salted per process, so a hash here would give the
        # same model different variable names on each run — the reproducibility
        # `val_idx` already goes out of its way to preserve.
        for si, (scope_name, scope_cells) in enumerate(self._scopes(cells)):
            self._apply_scope(model, link_any, scope_cells, len(dates),
                              scope_name, declared, si)

    def _scopes(self, cells):
        """The cell groups this rule constrains independently.

        Default: one group, exactly the cells the old single-``base_slot``
        filter selected. With ``per_base_slot`` each slot is its own group, so
        "the key ingredient must not come back for three days" binds the veg
        gravy against other veg gravies and not against the salad.
        """
        if not self.per_base_slot:
            scoped = [c for c in cells
                      if self.base_slots is None or c.base_slot in self.base_slots]
            name = ('+'.join(sorted(self.base_slots)) if self.base_slots
                    else 'all slots')
            return [(name, scoped)] if scoped else []
        by_slot: Dict[str, List[Any]] = defaultdict(list)
        for c in cells:
            if self.base_slots is not None and c.base_slot not in self.base_slots:
                continue
            if c.base_slot in CONST_SLOTS or c.base_slot in REPEATABLE_SLOTS:
                continue
            by_slot[c.base_slot].append(c)
        return sorted(by_slot.items())

    def _apply_scope(self, model, link_any, cells, n_days, scope_name,
                     declared, scope_idx=0):
        from .unique_items_menu_rule import matches_declared

        def value_of(row, base_slot):
            """The row's group value, or '' when it must not constrain.

            A dish declared repeatable is exempt: some rule has said it may
            recur, and a variety cap that then forbids it would be the two
            rules disagreeing about the same dish (note 19).
            """
            if (repeatable_row(row, base_slot)
                    or matches_declared(row, base_slot, declared)):
                return ''
            return _norm_cell(row.get(self.group_by, ''))

        # dv_bool[(day_index, value)] = bool var, true iff this scope takes an
        # item whose group_by value == `value` on that day (full reification
        # via link_any). Only build bools for (day, value) pairs that are
        # actually placeable.
        dv_bool: Dict[Any, Any] = {}
        values: set = set()
        val_idx: Dict[str, int] = {}  # stable, hash-seed-independent var names
        for di in range(n_days):
            day_cells = [c for c in cells if c.d_idx == di]
            if not day_cells:
                continue
            groups = defaultdict(list)
            for c in day_cells:
                for v, r in zip(c.x_vars, c.cand_rows):
                    val = value_of(r, c.base_slot)
                    if val:
                        groups[val].append(v)

            # `max_cells_per_day` counts CELLS, not days, so it is applied to
            # the raw literals — the day-bool below collapses "this value is on
            # the plate" to one variable and by construction cannot see the
            # same ingredient twice on one plate, which is the whole point here.
            if self.max_cells_per_day is not None:
                for val, lits in groups.items():
                    if len(lits) > self.max_cells_per_day:
                        model.Add(sum(lits) <= self.max_cells_per_day)

            for val, lits in groups.items():
                vi = val_idx.setdefault(val, len(val_idx))
                y = model.NewBoolVar(f'{self.name}_s{scope_idx}_d{di}_v{vi}')
                link_any(model, lits, y)
                dv_bool[(di, val)] = y
                values.add(val)

        if not dv_bool:
            return

        # Each distinct value appears on at most N days across the horizon.
        if self.max_per_group is not None:
            for val in values:
                lits = [dv_bool[(di, val)] for di in range(n_days) if (di, val) in dv_bool]
                if len(lits) > self.max_per_group:
                    model.Add(sum(lits) <= self.max_per_group)

        gap = self._gap
        if gap < 1:
            return
        window = gap + 1

        # The same value may not be chosen twice inside a sliding window of
        # `window` service days — UNLESS the days in it have nothing else to
        # switch to.
        #
        # A dal colour may repeat when no other colour is left in the pool. Once
        # the cooldown has removed the dals already served, a day can be down to
        # a single colour; banning the repeat then is not a preference the
        # solver can honour, it is an arithmetic impossibility that takes the
        # whole plan down (Amadeus Pune, week 3). If some day in the window
        # still has an alternative the ban is satisfiable and stays enforced —
        # the relaxation is scoped to the window that genuinely has no choice.
        day_values: Dict[int, set] = defaultdict(set)
        for (di, val) in dv_bool:
            day_values[di].add(val)

        # Scope-level check first. Filling `window` consecutive days without
        # repeating a value needs one distinct value per cell in the window, and
        # `unique_items` means each must also be a DIFFERENT dish. Pune's dal is
        # 32 dishes but 26 are yellow: only 6 non-yellow exist, so from week 3
        # alternation is impossible even though each day still shows two colours.
        # `nonveg_main` is the same shape by construction — six key ingredients
        # across the ontology against a mandated daily chicken gravy. Enforcing
        # it then kills the plan, so the rule stands down for this scope.
        dishes_by_value: Dict[str, set] = defaultdict(set)
        per_day = 0
        for c in cells:
            if c.d_idx == 0:
                per_day += 1
            for r in c.cand_rows:
                val = value_of(r, c.base_slot)
                if val:
                    dishes_by_value[val].add(_norm_str(str(r.get('item', ''))))
        per_day = max(1, per_day)
        if dishes_by_value:
            if gap == 1:
                # Alternation only needs the non-dominant values to cover every
                # other day — the long-standing check, kept exactly.
                sizes = sorted((len(v) for v in dishes_by_value.values()),
                               reverse=True)
                achievable = sum(sizes[1:]) >= n_days // 2
                shortfall = sum(sizes[1:])
                need = n_days // 2
            else:
                # A wider window needs a distinct value for every cell in it.
                achievable = len(dishes_by_value) >= per_day * min(window, n_days)
                shortfall = len(dishes_by_value)
                need = per_day * min(window, n_days)
            if not achievable:
                logger.info(
                    "%s: %s has only %d distinct %s against %d needed to keep "
                    "them apart for %d day(s) — not achievable, so the gap is "
                    "relaxed for that slot",
                    self.name, scope_name, shortfall, self.group_by, need, gap,
                    extra={RELAXATION: self.name},
                )
                return

        for start in range(n_days):
            span = [di for di in range(start, min(start + window, n_days))]
            if len(span) < 2:
                continue
            if max((len(day_values.get(di, ())) for di in span), default=0) < 2:
                logger.info(
                    "%s: days %d-%d of %s have no alternative %s left, so the "
                    "gap is relaxed for that window",
                    self.name, span[0], span[-1], scope_name, self.group_by,
                    extra={RELAXATION: self.name},
                )
                continue
            for val in values:
                lits = [dv_bool[(di, val)] for di in span if (di, val) in dv_bool]
                if len(lits) > 1:
                    model.Add(sum(lits) <= 1)

    # Populated by the diagnostics aggregator (see diagnostics.run_diagnostics).
    _peer_rules: List[Any] = []

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Report when this grouping cannot bite, or cannot be satisfied.

        The rule caps how often each distinct value of ``group_by`` may appear,
        so two things are worth saying out loud:

        * the attribute column is missing or empty in the eligible pool, so the
          rule constrains nothing (a silently inert variety rule);
        * there are fewer distinct values than the cap allows slots for, which
          means the cap has to be relaxed somewhere — the same arithmetic as a
          starved slot, reported so it isn't a surprise.
        """
        diags: List[Diagnostic] = []
        if not self.group_by or not self.base_slot:
            return diags
        active = ctx.active_base_slots
        if active is not None and self.base_slot not in active:
            return diags
        pool = ctx.pools.get(self.base_slot)
        if pool is None:
            return diags

        if self.group_by not in pool.columns:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"Column '{self.group_by}' is not present in the "
                    f"{self.base_slot} pool, so this grouping rule constrains "
                    f"nothing."
                ),
                suggestion=(
                    f"Add the '{self.group_by}' column to the ontology, correct "
                    f"the group_by name, or remove the rule."
                ),
                affected={'base_slot': self.base_slot, 'group_by': self.group_by},
            ))
            return diags

        values = {
            _norm_cell(v) for v in pool[self.group_by].dropna().tolist()
        }
        values.discard('')
        slot_counts = (
            ctx.client_cfg.slot_counts if ctx.client_cfg is not None else {}
        ) or {}
        per_day = int(slot_counts.get(self.base_slot, 1) or 1)
        planned_days = sum(
            1 for d in ctx.dates
            if (d, self.base_slot) not in (ctx.skip_cells or set())
        )
        cells = planned_days * per_day

        if not values:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"Every {self.base_slot} candidate has an empty "
                    f"'{self.group_by}', so this grouping rule constrains "
                    f"nothing."
                ),
                suggestion=(
                    f"Populate '{self.group_by}' for {self.base_slot} items in "
                    f"the ontology, or remove the rule."
                ),
                affected={'base_slot': self.base_slot, 'group_by': self.group_by},
            ))
            return diags

        if self.max_per_group is not None and cells:
            capacity = len(values) * self.max_per_group
            if capacity < cells:
                diags.append(Diagnostic(
                    rule=self.name, rule_type=self.rule_type.value,
                    severity=DiagnosticSeverity.WARNING,
                    phase=DiagnosticPhase.APPLY,
                    message=(
                        f"{self.base_slot} has {len(values)} distinct "
                        f"'{self.group_by}' value(s) capped at "
                        f"{self.max_per_group} each = {capacity} placements, but "
                        f"{cells} are needed. The cap cannot hold for every day."
                    ),
                    suggestion=(
                        f"Add {self.base_slot} items with more varied "
                        f"'{self.group_by}' values, widen source_pools, raise "
                        f"max_per_group, or shorten the horizon."
                    ),
                    affected={
                        'base_slot': self.base_slot,
                        'group_by': self.group_by,
                        'distinct_values': len(values),
                        'max_per_group': self.max_per_group,
                        'capacity': capacity,
                        'cells_needed': cells,
                    },
                ))
        return diags
