"""
Nonveg biryani weekly limit rule.

Ensures nonveg biryani appears at most once per week across all days.
"""

from typing import Dict, Any, List
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType
from ..preprocessor.column_mapper import _to_bool01


class NonvegBiryaniWeeklyRule(BaseMenuRule):
    """
    Config:
    {
        "type": "nonveg_biryani_weekly",
        "name": "nonveg_biryani_once_per_week",
        "max_per_week": 1
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COUPLING
        self.max_per_week = int(rule_config.get('max_per_week', 1))

    def validate_config(self) -> bool:
        return self.max_per_week >= 0

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')

        if not cells or not link_any:
            return

        biryani_day_vars = []

        for di in range(len(dates)):
            nv_cells = [c for c in cells if c.d_idx == di and c.base_slot == 'nonveg_main']
            if not nv_cells:
                continue

            biryani_lits = [
                v for c in nv_cells
                for v, r in zip(c.x_vars, c.cand_rows)
                if int(r.get('is_nonveg_biryani', 0)) == 1
            ]

            if biryani_lits:
                day_has_biryani = model.NewBoolVar(f'nonveg_biryani_day_{di}')
                link_any(model, biryani_lits, day_has_biryani)
                biryani_day_vars.append(day_has_biryani)

        if biryani_day_vars:
            model.Add(sum(biryani_day_vars) <= self.max_per_week)
