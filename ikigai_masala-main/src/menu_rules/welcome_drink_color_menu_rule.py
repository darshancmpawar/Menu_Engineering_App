"""
Welcome drink color rule: no consecutive-day same color for welcome drinks.
"""

from typing import Dict, Any
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class WelcomeDrinkColorMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "welcome_drink_color",
        "name": "welcome_drink_no_repeat_color"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.WELCOME_DRINK_COLOR

    def validate_config(self) -> bool:
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        dates = context.get('dates', [])
        known_welcome_colors = context.get('known_welcome_colors', [])
        day_welcome_color_vars = context.get('day_welcome_color_vars', {})

        for di in range(len(dates) - 1):
            for col in known_welcome_colors:
                a = day_welcome_color_vars.get((di, col), [])
                b = day_welcome_color_vars.get((di + 1, col), [])
                if a and b:
                    model.Add(sum(a) + sum(b) <= 1)
