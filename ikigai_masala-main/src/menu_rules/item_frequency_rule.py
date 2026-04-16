"""
Item frequency rule: cap how many days per week contain a matching item.

CP-SAT phase rule — adds cardinality constraints on a selector-matched
set of candidates.  Supports ``min_per_week`` and/or ``max_per_week``.

**Day-level semantics**: counts are "how many days have >= 1 matching item",
not total occurrences.  For slots with count=1/day this is equivalent.
"""

from typing import Dict, Any, List, Optional, Tuple

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType
from ..preprocessor.column_mapper import _norm_str


_SELECTOR_KEYS = frozenset({'flag', 'sub_category', 'item', 'key_ingredient'})


class ItemFrequencyRule(BaseMenuRule):
    """
    Config example::

        {
            "type": "item_frequency",
            "name": "tekion_liquid_rice_once",
            "base_slot": "rice",
            "selector": {"flag": "is_liquid_rice"},
            "min_per_week": 1,
            "max_per_week": 1
        }

    Selector must contain exactly one key from:
    ``flag``, ``sub_category``, ``item``, ``key_ingredient``.
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.ITEM_FREQUENCY

        sel = rule_config.get('selector', {})
        present = [k for k in _SELECTOR_KEYS if k in sel]
        if len(present) == 1:
            self.sel_kind: str = present[0]
            raw_val = sel[self.sel_kind]
            # For flag selectors the value is the column name (kept as-is).
            # For text selectors the value is normalised for matching.
            self.sel_value: str = raw_val if self.sel_kind == 'flag' else _norm_str(str(raw_val))
        else:
            self.sel_kind = ''
            self.sel_value = ''

        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self.min_per_week: Optional[int] = (
            int(rule_config['min_per_week']) if 'min_per_week' in rule_config else None
        )
        self.max_per_week: Optional[int] = (
            int(rule_config['max_per_week']) if 'max_per_week' in rule_config else None
        )

    def validate_config(self) -> bool:
        if not self.sel_kind:
            return False
        if self.min_per_week is None and self.max_per_week is None:
            return False
        if self.min_per_week is not None and self.min_per_week < 0:
            return False
        if self.max_per_week is not None and self.max_per_week < 0:
            return False
        return True

    # -- matching helpers --

    def _row_matches(self, row) -> bool:
        """Return True if a candidate row matches the selector."""
        if self.sel_kind == 'flag':
            return int(row.get(self.sel_value, 0)) == 1
        col_map = {
            'sub_category': 'sub_category',
            'item': 'item',
            'key_ingredient': 'key_ingredient',
        }
        col = col_map.get(self.sel_kind, '')
        return _norm_str(str(row.get(col, ''))) == self.sel_value

    # -- CP-SAT --

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')

        if not cells or not link_any:
            return

        day_vars: List = []

        for di in range(len(dates)):
            day_cells = [
                c for c in cells
                if c.d_idx == di
                and (self.base_slot is None or c.base_slot == self.base_slot)
            ]
            if not day_cells:
                continue

            matching_lits = [
                v
                for c in day_cells
                for v, r in zip(c.x_vars, c.cand_rows)
                if self._row_matches(r)
            ]

            if matching_lits:
                day_has = model.NewBoolVar(f'{self.name}_day_{di}')
                link_any(model, matching_lits, day_has)
                day_vars.append(day_has)

        if not day_vars:
            return

        if self.max_per_week is not None:
            model.Add(sum(day_vars) <= self.max_per_week)
        if self.min_per_week is not None:
            model.Add(sum(day_vars) >= self.min_per_week)
