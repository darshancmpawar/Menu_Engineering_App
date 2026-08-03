"""Same-day exclusion: two families of dish may not share a day.

Some dishes read as substitutes for each other, so serving both on one day wastes
a slot from the diner's point of view. Paneer and the other "premium protein"
dishes are the case this was built for::

    {
        "type": "same_day_exclusion",
        "name": "paneer_not_with_soya_babycorn_chole_mushroom",
        "selector": {"key_ingredient": "paneer"},
        "exclude": {"any_of": [
            {"key_ingredient": "soy"},
            {"key_ingredient": "baby_corn"},
            {"flag": "is_chana_gravy"},
            {"key_ingredient": "mushroom"}
        ]}
    }

Semantics: on any day the *selector* appears, nothing matching *exclude* may
appear, and vice versa. Counted across every slot unless ``base_slot`` /
``exclude_base_slot`` narrow it, because the point is the day's plate as a whole:
a paneer gravy next to a soya veg dry is exactly what this forbids.

HARD, with one relaxation, and it is the arithmetic kind rather than a fallback:
a day is skipped when BOTH sides are *forced* — some slot that day has no
candidate outside `exclude`, and some slot has none outside `selector`. Then no
choice satisfies the rule and enforcing it would only turn a reportable
impossibility into a bare INFEASIBLE. Anything else (a composition mandating a
matching dish, say) is left to fail loudly, which is the designed behaviour for
an over-constrained counter.

Why not ``soft_preference`` with ``mode: different_day``: that penalises the pair
rather than forbidding it, so a high enough gain elsewhere buys the violation.
"Don't serve them together" is a constraint.
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

logger = logging.getLogger(__name__)


class SameDayExclusionRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SAME_DAY_EXCLUSION
        self._sel = SelectorFrequencyRule._parse_matcher(rule_config.get('selector'))
        self._exc = SelectorFrequencyRule._parse_matcher(rule_config.get('exclude'))
        # Optional narrowing: by default both sides are counted across every slot.
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self.exclude_base_slot: Optional[str] = rule_config.get('exclude_base_slot')

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if self._sel is None:
            errs.append("a valid 'selector' is required")
        if self._exc is None:
            errs.append("a valid 'exclude' is required")
        return errs

    # ----- helpers -----

    @staticmethod
    def _day_cells(cells, di, base_slot):
        return [
            c for c in cells
            if c.d_idx == di and (base_slot is None or c.base_slot == base_slot)
        ]

    @staticmethod
    def _hits(row, matcher, not_matcher) -> bool:
        """Does *row* count for *matcher*, ignoring rows that are also
        *not_matcher*?

        A dish can satisfy both sides at once — `chole_paneer` is
        `key_ingredient: paneer` AND `is_chana_gravy`. It is ONE dish, so it
        cannot "be served alongside itself", and counting it on both sides makes
        `a + b <= 1` read `1 + 1 <= 1`: the dish becomes unservable anywhere, on
        every counter, silently. Such a dish belongs to the selector (a chole
        paneer curry is a paneer dish), so it is dropped from the exclude side.
        """
        if not SelectorFrequencyRule._matches(row, matcher):
            return False
        return not (
            not_matcher is not None
            and SelectorFrequencyRule._matches(row, not_matcher)
        )

    @classmethod
    def _lits(cls, day_cells, matcher, not_matcher=None):
        out = []
        for c in day_cells:
            for v, r in zip(c.x_vars, c.cand_rows):
                if cls._hits(r, matcher, not_matcher):
                    out.append(v)
        return out

    @classmethod
    def _forced(cls, day_cells, matcher, not_matcher=None) -> bool:
        """True when some cell has NO candidate outside *matcher*.

        That cell must take a matching dish whatever the solver does, so the
        matcher's day-indicator is pinned to 1.
        """
        for c in day_cells:
            rows = list(c.cand_rows)
            if rows and all(cls._hits(r, matcher, not_matcher) for r in rows):
                return True
        return False

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')
        if not cells or not dates or link_any is None:
            return
        if self._sel is None or self._exc is None:
            return

        for di in range(len(dates)):
            sel_cells = self._day_cells(cells, di, self.base_slot)
            exc_cells = self._day_cells(cells, di, self.exclude_base_slot)
            sel_lits = self._lits(sel_cells, self._sel)
            exc_lits = self._lits(exc_cells, self._exc, self._sel)
            if not sel_lits or not exc_lits:
                continue    # one side cannot occur today; nothing to exclude
            if self._forced(sel_cells, self._sel) and \
                    self._forced(exc_cells, self._exc, self._sel):
                logger.info(
                    "%s: day %d has a slot with only %s candidates AND a slot "
                    "with only %s candidates, so both sides are unavoidable; "
                    "skipping the exclusion for this day rather than making the "
                    "plan INFEASIBLE",
                    self.name, di, self._sel, self._exc,
                )
                continue
            a = model.NewBoolVar(f'{self.name}_sel_{di}')
            b = model.NewBoolVar(f'{self.name}_exc_{di}')
            link_any(model, sel_lits, a)
            link_any(model, exc_lits, b)
            model.Add(a + b <= 1)

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Report a side that matches nothing — an exclusion between a real family
        and an empty one silently constrains nothing."""
        diags: List[Diagnostic] = []
        if self._sel is None or self._exc is None:
            return diags
        slots = list(ctx.active_base_slots or ctx.pools.keys())

        def count(matcher, only_slot, not_matcher=None):
            total = 0
            for base in slots:
                if only_slot is not None and base != only_slot:
                    continue
                pool = ctx.pools.get(base)
                if pool is None or not len(pool):
                    continue
                total += sum(
                    1 for _i, row in pool.iterrows()
                    if self._hits(row, matcher, not_matcher)
                )
            return total

        n_sel = count(self._sel, self.base_slot)
        # Same overlap rule as apply(), so the report and the solve agree: a dish
        # matching both sides counts only as the selector.
        n_exc = count(self._exc, self.exclude_base_slot, self._sel)
        if n_sel and n_exc:
            return diags
        empty = 'selector' if not n_sel else 'exclude'
        diags.append(Diagnostic(
            rule=self.name, rule_type=self.rule_type.value,
            severity=DiagnosticSeverity.INFO,
            phase=DiagnosticPhase.APPLY,
            message=(
                f"No eligible item matches this rule's {empty} side "
                f"(selector matches {n_sel}, exclude matches {n_exc}), so the "
                f"exclusion is inert for this counter."
            ),
            suggestion=(
                "Expected when a city's item list does not carry that family "
                "(Pune has no mushroom dishes, for example). Check the selector "
                "against the ontology columns if it should be matching."
            ),
            affected={
                'selector_matches': n_sel, 'exclude_matches': n_exc,
                'base_slot': self.base_slot,
                'exclude_base_slot': self.exclude_base_slot,
            },
        ))
        return diags
