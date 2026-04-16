"""
Ingredient ban rule: drop items whose key_ingredient matches a banned list.

Pre-filter phase rule — case-insensitive exact match on the normalised
``key_ingredient`` column.  Banning ``"corn"`` does NOT affect ``"babycorn"``
because matches are on the full value, not a substring.
"""

import datetime as dt
import pandas as pd
from typing import Dict, Any, Set

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class IngredientBanRule(BaseMenuRule):
    """
    Config example::

        {
            "type": "ingredient_ban",
            "name": "tekion_no_mushroom",
            "ingredients": ["mushroom"]
        }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.INGREDIENT_BAN
        raw = rule_config.get('ingredients', [])
        self.banned: Set[str] = {i.strip().lower() for i in raw if isinstance(i, str)}

    def validate_config(self) -> bool:
        return (
            isinstance(self.config.get('ingredients'), list)
            and len(self.banned) > 0
        )

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        if len(pool) == 0 or 'key_ingredient' not in pool.columns or not self.banned:
            return pool
        ki = pool['key_ingredient'].astype(str).str.strip().str.lower()
        return pool[~ki.isin(self.banned)]

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool
