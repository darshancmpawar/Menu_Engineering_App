"""
Theme day menu rule: Monday mix enforcement.

On 'mix' days (Monday), ensures at least 1 south-cuisine item and
1 north-cuisine item among non-exempt slots.
"""

from typing import Dict, Any
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class ThemeDayMenuRule(BaseMenuRule):
    """
    Enforces Monday mix constraint: >= 1 south + >= 1 north item.

    Config:
    {
        "type": "theme_day",
        "name": "monday_mix"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_DAY

    def validate_config(self) -> bool:
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        day_types = context.get('day_types', [])
        south_lits = context.get('monday_south_lits', [])
        north_lits = context.get('monday_north_lits', [])

        if any(dt == 'mix' for dt in day_types):
            if south_lits:
                model.Add(sum(south_lits) >= 1)
            if north_lits:
                model.Add(sum(north_lits) >= 1)
