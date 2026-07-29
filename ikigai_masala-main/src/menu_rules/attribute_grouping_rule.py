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

Config::

    {
        "type": "attribute_grouping",
        "name": "dal_colour_non_consecutive",
        "base_slot": "dal",           # slot to scope to (required in practice)
        "group_by": "item_color",     # attribute column defining the groups
        "non_consecutive": true,      # same value may not be on adjacent days
        "max_per_group": null         # each value appears on <= N days / horizon
    }

At least one of ``non_consecutive`` / ``max_per_group`` must be set. Both are
caps — they never *force* a value to appear — so the rule can only tighten a
model, never make it infeasible on its own (a same-value adjacency ban can
still bite if a day's pool collapses to one value, which the pre-flight
diagnostics are there to surface).
"""

import logging
from collections import defaultdict
from typing import Dict, Any, List, Optional

from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from ..preprocessor.column_mapper import _norm_str

logger = logging.getLogger(__name__)


class AttributeGroupingRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.ATTRIBUTE_GROUPING
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self.group_by: str = str(rule_config.get('group_by') or '')
        self.non_consecutive: bool = bool(rule_config.get('non_consecutive', False))
        mpg = rule_config.get('max_per_group')
        self.max_per_group: Optional[int] = int(mpg) if mpg is not None else None

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.group_by:
            errs.append("group_by (an attribute column name) is required")
        if not self.non_consecutive and self.max_per_group is None:
            errs.append("at least one of non_consecutive / max_per_group is required")
        if self.max_per_group is not None and self.max_per_group < 0:
            errs.append(f"max_per_group must be >= 0 (got {self.max_per_group})")
        return errs

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')
        if not cells or not link_any or not self.group_by:
            return

        # dv_bool[(day_index, value)] = bool var, true iff this slot takes an
        # item whose group_by value == `value` on that day (full reification
        # via link_any). Only build bools for (day, value) pairs that are
        # actually placeable.
        dv_bool: Dict[Any, Any] = {}
        values: set = set()
        val_idx: Dict[str, int] = {}  # stable, hash-seed-independent var names
        n_days = len(dates)
        for di in range(n_days):
            day_cells = [
                c for c in cells
                if c.d_idx == di and (self.base_slot is None or c.base_slot == self.base_slot)
            ]
            if not day_cells:
                continue
            groups = defaultdict(list)
            for c in day_cells:
                for v, r in zip(c.x_vars, c.cand_rows):
                    val = _norm_str(str(r.get(self.group_by, '')))
                    if val:
                        groups[val].append(v)
            for val, lits in groups.items():
                vi = val_idx.setdefault(val, len(val_idx))
                y = model.NewBoolVar(f'{self.name}_d{di}_v{vi}')
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

        # The same value may not be chosen on two adjacent service days.
        if self.non_consecutive:
            for di in range(n_days - 1):
                for val in values:
                    a = dv_bool.get((di, val))
                    b = dv_bool.get((di + 1, val))
                    if a is not None and b is not None:
                        model.Add(a + b <= 1)

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
            _norm_str(str(v)) for v in pool[self.group_by].dropna().tolist()
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
