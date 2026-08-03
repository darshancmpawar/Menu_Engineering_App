"""Generic config-driven soft-preference rule (Phase-4 soft-rule framework).

A soft rule only *shapes the objective* — it can never make the model
infeasible. This one class covers the rulebook's common soft patterns via a
``mode``, so preferences live in config instead of one class each:

  * ``different_day`` — penalise two selectors landing on the same day
    (rulebook soft #3: keep Premium Veg Gravy and Premium Veg Dry apart).
  * ``avoid_consecutive`` — penalise a selector appearing on adjacent days
    (soft #14-17: don't repeat a regional Non-Veg Main / Flavoured Rice
    back-to-back).
  * ``avoid_attribute_repeat`` — penalise a slot repeating an attribute value
    across the horizon (soft #1: vary the key ingredient).

Config::

    {
        "type": "soft_preference",
        "name": "premiums_different_days",
        "mode": "different_day",
        "weight": 300000,
        "selector_a": {"flag": "is_premium_gravy"}, "base_slot_a": "veg_gravy",
        "selector_b": {"flag": "is_premium_veg_dry"}, "base_slot_b": "veg_dry"
    }

``weight`` is the per-violation penalty. Defaults sit **below** the theme
mega-weights (~1e6) so theme adherence always wins, and **above** the random
tie-breaker (~1e3/cell) so the preference actually takes effect. A true
priority-tier (lexicographic) objective is the proper long-term fix; until
then these weights are a documented approximation.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from ortools.sat.python import cp_model

from .base_menu_rule import BaseMenuRule, MenuRuleType, MenuRuleSeverity
from .selector_frequency_rule import SelectorFrequencyRule
from ..constants import OBJECTIVE_TIER_WEIGHTS
from ..preprocessor.column_mapper import _norm_str

logger = logging.getLogger(__name__)

_MODES = frozenset({
    'different_day', 'avoid_consecutive', 'avoid_attribute_repeat',
    'prefer_day_types',
})


class SoftPreferenceRule(BaseMenuRule):
    severity = MenuRuleSeverity.SOFT

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SOFT_PREFERENCE
        self.mode: str = str(rule_config.get('mode') or '')
        # `priority` (high/medium/low) selects a weight tier so soft rules are
        # applied lexicographically; an explicit `weight` overrides it.
        self.priority: str = str(rule_config.get('priority', 'medium')).lower()
        _tier = OBJECTIVE_TIER_WEIGHTS.get(self.priority, OBJECTIVE_TIER_WEIGHTS['medium'])
        self.weight: int = int(rule_config.get('weight', _tier))
        # avoid_consecutive
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self._sel = SelectorFrequencyRule._parse_matcher(rule_config.get('selector'))
        # different_day
        self.base_slot_a: Optional[str] = rule_config.get('base_slot_a')
        self.base_slot_b: Optional[str] = rule_config.get('base_slot_b')
        self._sel_a = SelectorFrequencyRule._parse_matcher(rule_config.get('selector_a'))
        self._sel_b = SelectorFrequencyRule._parse_matcher(rule_config.get('selector_b'))
        # avoid_attribute_repeat
        self.group_by: Optional[str] = rule_config.get('group_by')
        # prefer_day_types — the themes this selector BELONGS on. Every other day
        # is penalised, so the others become the fallback rather than being
        # forbidden (which is what `selector_frequency.allowed_day_types` does).
        pdt = rule_config.get('day_types')
        self.day_types: Optional[Set[str]] = (
            {str(t).strip().lower() for t in pdt} if pdt else None
        )

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        return  # objective-only

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if self.mode not in _MODES:
            errs.append("mode must be one of " + ", ".join(sorted(_MODES)))
        if self.priority not in OBJECTIVE_TIER_WEIGHTS:
            errs.append("priority must be one of " + ", ".join(OBJECTIVE_TIER_WEIGHTS))
        if self.weight < 0:
            errs.append(f"weight must be >= 0 (got {self.weight})")
        if self.mode == 'different_day' and not (self._sel_a and self._sel_b):
            errs.append("different_day requires selector_a and selector_b")
        if self.mode == 'avoid_consecutive' and not self._sel:
            errs.append("avoid_consecutive requires selector")
        if self.mode == 'avoid_attribute_repeat' and not self.group_by:
            errs.append("avoid_attribute_repeat requires group_by")
        if self.mode == 'prefer_day_types':
            if not self._sel:
                errs.append("prefer_day_types requires selector")
            if not self.day_types:
                errs.append("prefer_day_types requires a non-empty day_types")
        return errs

    # ----- helpers -----

    def _day_slot_lits(self, cells, di, base_slot, matcher):
        """Item vars in (day di, base_slot) whose row matches `matcher`."""
        out = []
        for c in cells:
            if c.d_idx != di or (base_slot is not None and c.base_slot != base_slot):
                continue
            for v, r in zip(c.x_vars, c.cand_rows):
                if SelectorFrequencyRule._matches(r, matcher):
                    out.append(v)
        return out

    def get_objective_terms(self, model: cp_model.CpModel,
                            context: Dict[str, Any]) -> List:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')
        if not cells or not link_any or self.mode not in _MODES:
            return []
        w = self.weight
        n = len(dates)

        if self.mode == 'different_day':
            both_bools = []
            for di in range(n):
                a_lits = self._day_slot_lits(cells, di, self.base_slot_a, self._sel_a)
                b_lits = self._day_slot_lits(cells, di, self.base_slot_b, self._sel_b)
                if not a_lits or not b_lits:
                    continue
                a = model.NewBoolVar(f'{self.name}_a_{di}')
                b = model.NewBoolVar(f'{self.name}_b_{di}')
                link_any(model, a_lits, a)
                link_any(model, b_lits, b)
                both = model.NewBoolVar(f'{self.name}_both_{di}')
                model.Add(both >= a + b - 1)
                model.Add(both <= a)
                model.Add(both <= b)
                both_bools.append(both)
            return [sum(both_bools) * (-abs(w))] if both_bools else []

        if self.mode == 'prefer_day_types':
            # One penalty per off-theme day the selector lands on. Soft on
            # purpose: a hard version is `selector_frequency.allowed_day_types`,
            # and that forbids the dish outright — the ask here is "prefer these
            # days, fall back to the others", so the others must stay legal.
            day_types = context.get('day_types') or []
            off = []
            for di in range(n):
                dtype = str(day_types[di] if di < len(day_types) else '').lower()
                if dtype in self.day_types:
                    continue
                lits = self._day_slot_lits(cells, di, self.base_slot, self._sel)
                if not lits:
                    continue
                h = model.NewBoolVar(f'{self.name}_off_{di}')
                link_any(model, lits, h)
                off.append(h)
            return [sum(off) * (-abs(w))] if off else []

        if self.mode == 'avoid_consecutive':
            day_has = {}
            for di in range(n):
                lits = self._day_slot_lits(cells, di, self.base_slot, self._sel)
                if lits:
                    h = model.NewBoolVar(f'{self.name}_h_{di}')
                    link_any(model, lits, h)
                    day_has[di] = h
            pair_bools = []
            for di in range(n - 1):
                a, b = day_has.get(di), day_has.get(di + 1)
                if a is None or b is None:
                    continue
                both = model.NewBoolVar(f'{self.name}_adj_{di}')
                model.Add(both >= a + b - 1)
                model.Add(both <= a)
                model.Add(both <= b)
                pair_bools.append(both)
            return [sum(pair_bools) * (-abs(w))] if pair_bools else []

        # avoid_attribute_repeat: penalise each day a value recurs beyond the
        # first (over_v = max(0, days_with_value - 1)).
        per_val_days = defaultdict(list)
        for di in range(n):
            groups = defaultdict(list)
            for c in cells:
                if c.d_idx != di or (self.base_slot is not None and c.base_slot != self.base_slot):
                    continue
                for v, r in zip(c.x_vars, c.cand_rows):
                    val = _norm_str(str(r.get(self.group_by, '')))
                    if val:
                        groups[val].append(v)
            for val, lits in groups.items():
                h = model.NewBoolVar(f'{self.name}_{di}_{len(per_val_days)}')
                link_any(model, lits, h)
                per_val_days[val].append(h)
        over_terms = []
        for val, hs in per_val_days.items():
            if len(hs) < 2:
                continue
            over = model.NewIntVar(0, len(hs), f'{self.name}_over_{len(over_terms)}')
            model.Add(over >= sum(hs) - 1)
            over_terms.append(over)
        return [sum(over_terms) * (-abs(w))] if over_terms else []
