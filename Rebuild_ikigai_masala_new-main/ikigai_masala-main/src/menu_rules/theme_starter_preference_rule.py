"""
Theme starter preference soft constraint.

Adds bonus to objective for theme-matching starters.
"""

from typing import Dict, Any, List
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class ThemeStarterPreferenceRule(BaseMenuRule):
    """
    Config:
    {
        "type": "theme_starter_preference",
        "name": "prefer_theme_starters",
        "bonus_weight": 1000000
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_STARTER_PREFERENCE
        self.bonus_weight = rule_config.get('bonus_weight', 1000000)

    def validate_config(self) -> bool:
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # This rule contributes to objective only

    def get_objective_terms(self, model: cp_model.CpModel,
                           context: Dict[str, Any]) -> List:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        find_cells = context.get('find_cells_fn')
        link_any = context.get('link_any_fn')
        cfg = context.get('cfg')

        if not find_cells or not link_any or not cfg or not cfg.prefer_theme_starter:
            return []

        ok_vars = []
        for di in range(len(dates)):
            for idx, scell in enumerate(find_cells(cells, di, 'starter'), start=1):
                lits = [v for v, pref in zip(scell.x_vars, scell.theme_pref_flags) if pref]
                if lits:
                    ok = model.NewBoolVar(f'starter_theme_ok_{di}_{idx}')
                    link_any(model, lits, ok)
                    ok_vars.append(ok)

        if ok_vars:
            return [sum(ok_vars) * self.bonus_weight]
        return []
