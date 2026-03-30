"""
Color pairing menu rule: prevent same color for two course types on the same day.

Uses the cell-based context from the solver.
"""

import logging
from typing import Dict, Any

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType
from ..preprocessor.column_mapper import _norm_color

logger = logging.getLogger(__name__)


class ColorPairingMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "color_pairing",
        "name": "starter_main_color_mismatch",
        "course_type_a": "starter",
        "course_type_b": "veg_gravy"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.COLOR_PAIRING
        self.course_type_a = rule_config.get('course_type_a', '')
        self.course_type_b = rule_config.get('course_type_b', '')

    def validate_config(self) -> bool:
        if not self.course_type_a or not self.course_type_b:
            return False
        if self.course_type_a == self.course_type_b:
            return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        find_cells = context.get('find_cells_fn')
        cfg = context.get('cfg')

        if not cells or not find_cells or not cfg:
            return

        color_col = cfg.color_col

        for di in range(len(dates)):
            cells_a = find_cells(cells, di, self.course_type_a)
            cells_b = find_cells(cells, di, self.course_type_b)
            if not cells_a or not cells_b:
                continue

            # Group variables by color for each course type
            colors_a: Dict[str, list] = {}
            for c in cells_a:
                for var, row in zip(c.x_vars, c.cand_rows):
                    col = _norm_color(row.get(color_col, 'unknown'))
                    if col != 'unknown':
                        colors_a.setdefault(col, []).append(var)

            colors_b: Dict[str, list] = {}
            for c in cells_b:
                for var, row in zip(c.x_vars, c.cand_rows):
                    col = _norm_color(row.get(color_col, 'unknown'))
                    if col != 'unknown':
                        colors_b.setdefault(col, []).append(var)

            # For each shared color: at most one side can select it
            for color in set(colors_a) & set(colors_b):
                model.Add(sum(colors_a[color]) + sum(colors_b[color]) <= 1)
