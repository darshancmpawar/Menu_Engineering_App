"""
Theme fallback penalty soft constraint.

Penalizes non-theme items in starter/veg_dry slots. The solver exposes
``theme_fallback_bools`` on the context — one bool per (day, slot) that is
true when the chosen item is a non-theme fallback. This rule contributes a
negative objective term proportional to their sum.
"""

from typing import Dict, Any, List

from ortools.sat.python import cp_model

from .base_menu_rule import BaseMenuRule, MenuRuleType


class ThemeFallbackPenaltyRule(BaseMenuRule):
    """
    Config:
    {
        "type": "theme_fallback_penalty",
        "name": "penalize_non_theme_fallback",
        "penalty": 2000000
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_FALLBACK_PENALTY
        self.penalty = rule_config.get('penalty', 2000000)

    def validate_config(self) -> bool:
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        return

    def get_objective_terms(self, model: cp_model.CpModel,
                            context: Dict[str, Any]) -> List:
        fallback_bools = context.get('theme_fallback_bools') or []
        if not fallback_bools:
            return []
        return [sum(fallback_bools) * (-abs(int(self.penalty)))]
