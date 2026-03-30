"""
Color variety menu rule: minimum distinct colors per day.

Uses day_color_vars from solver context.
"""

import logging
from typing import Dict, Any

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType

logger = logging.getLogger(__name__)


class ColorVarietyMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "color_variety",
        "name": "daily_color_variety",
        "min_distinct_colors": {"lunch": 3}
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COLOR_VARIETY
        self.min_distinct_colors = rule_config.get('min_distinct_colors', None)

    def validate_config(self) -> bool:
        if not isinstance(self.min_distinct_colors, dict) or not self.min_distinct_colors:
            return False
        for val in self.min_distinct_colors.values():
            try:
                if int(val) <= 0:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        dates = context.get('dates', [])
        known_colors = context.get('known_colors', [])
        day_color_vars = context.get('day_color_vars', {})
        link_any = context.get('link_any_fn')

        if not dates or not known_colors or not link_any:
            return

        # Resolve min distinct colors for the current meal type
        meal_type = context.get('meal_type', '')
        min_colors = 0
        if isinstance(self.min_distinct_colors, dict) and meal_type:
            try:
                min_colors = int(self.min_distinct_colors.get(meal_type, 0))
            except (TypeError, ValueError):
                pass
        if min_colors <= 0:
            return

        for di in range(len(dates)):
            y_vars = []
            for col in known_colors:
                lits = day_color_vars.get((di, col), [])
                if not lits:
                    continue
                y = model.NewBoolVar(f'cv_y_{di}_{col}')
                link_any(model, lits, y)
                y_vars.append(y)
            if y_vars:
                model.Add(sum(y_vars) >= min_colors)
