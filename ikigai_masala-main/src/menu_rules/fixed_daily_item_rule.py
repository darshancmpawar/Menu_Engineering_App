"""Fixed-daily-item rule: one slot's dish is the SAME every day.

Some dishes are a fixture rather than a variety slot. L&T's five-dish non-veg
station serves the same ``CHICKEN KABAB`` and the same ``EGG CURRY`` every day of
the week — its printed menu shows both rows identical across all five columns.

The kebab already behaves that way by accident: only one tandoor item is eligible
for a common-only client, so there is nothing to vary. The egg does not — 21 egg
dishes are eligible, so exempting egg from ``unique_items`` merely *permits* a
repeat without producing one, and the solver is free to serve five different egg
curries. This rule makes it deliberate::

    {
        "type": "fixed_daily_item",
        "name": "lt_egg_same_every_day",
        "base_slot": "nonveg_main",
        "selector": {"flag": "is_egg_dish"}
    }

Semantics: across the horizon, the dish chosen for the *matching* part of
``base_slot`` is the same item every day it appears. It does not force the dish to
appear — whatever mandates it (here the ``slot_composition`` egg component) keeps
that job — it only forces consistency.

Encoding: one bool ``z_i`` per matching candidate item, plus
``sum(that item's vars on day d) == z_i`` for every day. So an item is either used
on every day (``z_i = 1``) or on none (``z_i = 0``), and a slot family with one
matching cell per day lands exactly one fixed dish.

The rule also declares its items repeatable, via
:py:meth:`repeatable_item_flags`, because ``unique_items`` would otherwise forbid
the very repetition this rule exists to create. That declaration is read by the
solver when it assembles the repeatable set, so the two rules cannot disagree.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from .selector_frequency_rule import SelectorFrequencyRule
from ..preprocessor.column_mapper import _norm_str

logger = logging.getLogger(__name__)


class FixedDailyItemRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.FIXED_DAILY_ITEM
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self._inc = SelectorFrequencyRule._parse_matcher(rule_config.get('selector'))
        self._exc = SelectorFrequencyRule._parse_matcher(rule_config.get('exclude'))

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.base_slot:
            errs.append("base_slot is required")
        if self._inc is None:
            errs.append("a valid 'selector' is required")
        return errs

    def _row_matches(self, row) -> bool:
        return (SelectorFrequencyRule._matches(row, self._inc)
                and not SelectorFrequencyRule._matches(row, self._exc))

    def repeatable_item_flags(self) -> Dict[str, Any]:
        """What this rule needs exempted from ``unique_items``.

        Returns ``{base_slot: matcher}``. The solver folds these into the
        repeatable set so uniqueness does not forbid the repetition this rule
        creates. Declared rather than hard-coded in ``constants`` so the
        exemption is scoped to the client that asked for it.
        """
        if not self.base_slot or self._inc is None:
            return {}
        return {self.base_slot: (self._inc, self._exc)}

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        if not cells or not dates or not self.base_slot or self._inc is None:
            return

        # Group this slot family's matching vars per (item, day).
        by_item: Dict[str, Dict[int, List[Any]]] = {}
        for cell in cells:
            if cell.base_slot != self.base_slot:
                continue
            for var, row in zip(cell.x_vars, cell.cand_rows):
                if not self._row_matches(row):
                    continue
                name = _norm_str(row.get('item', ''))
                if name:
                    by_item.setdefault(name, {}).setdefault(cell.d_idx, []).append(var)

        if not by_item:
            logger.info(
                "%s: no candidate in %r matches the selector; rule is inert",
                self.name, self.base_slot)
            return

        # An item is used on every day or on none. Days on which the item has no
        # candidate at all cannot host it, so it is excluded from the fixed
        # choice entirely rather than making the model INFEASIBLE.
        #
        # "Every day" means every day THIS SLOT IS SERVED, not every day in the
        # horizon. Using the horizon length breaks the moment the slot also has a
        # `slot_day_restriction`: Amadeus Pune serves bread Mon-Sat, so over a
        # 7-day horizon chapati appeared on 6 of 7 days, was judged ineligible,
        # and was pinned to zero — leaving the six bread cells with no candidate
        # at all. Every candidate failing that way is an INFEASIBLE plan.
        slot_days = {
            cell.d_idx for cell in cells if cell.base_slot == self.base_slot
        }
        n_days = len(slot_days) or len(dates)
        eligible = 0
        for name, per_day in sorted(by_item.items()):
            if len(per_day) < n_days:
                for vars_ in per_day.values():
                    model.Add(sum(vars_) == 0)
                continue
            eligible += 1
            z = model.NewBoolVar(f'{self.name}_fixed_{name}'[:190])
            for _di, vars_ in sorted(per_day.items()):
                model.Add(sum(vars_) == z)

        if eligible == 0:
            logger.warning(
                "%s: no item matching the selector is available on all %d day(s), "
                "so no dish can be held fixed; the rule is inert this horizon.",
                self.name, n_days)

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Report when no matching dish can be held fixed across the horizon."""
        diags: List[Diagnostic] = []
        if not self.base_slot or self._inc is None:
            return diags
        active = ctx.active_base_slots
        if active is not None and self.base_slot not in active:
            return diags
        pool = ctx.pools.get(self.base_slot)
        if pool is None or not len(pool):
            return diags

        matching = [r for _i, r in pool.iterrows() if self._row_matches(r)]
        sel = f"{self._inc[0]}={self._inc[1]!r}"
        if not matching:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"No eligible '{self.base_slot}' item matches {sel}, so there "
                    f"is no dish to hold fixed and this rule is inert."
                ),
                suggestion=(
                    "Check the selector against the ontology columns, or remove "
                    "the rule."
                ),
                affected={'base_slot': self.base_slot, 'selector': sel},
            ))
        return diags
