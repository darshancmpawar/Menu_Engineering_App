"""
Theme fallback penalty soft constraint.

Penalizes non-theme items in starter/veg_dry slots.
The penalty is applied via theme_fallback_bools already computed
in _build_decision_variables, so this rule is a no-op for apply()
but the penalty is built into the solver objective directly.
"""

from typing import Dict, Any
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
        pass  # Penalty is applied via cfg.theme_fallback_penalty in solver objective
