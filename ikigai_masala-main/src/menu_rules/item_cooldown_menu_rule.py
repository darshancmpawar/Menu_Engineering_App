"""
Item cooldown rule: ban items used within the last N days.

Pre-filter phase rule — removes recently-used items from candidate pools.
"""

import datetime as dt
import pandas as pd
from typing import Dict, Any, Set

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class ItemCooldownMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "item_cooldown",
        "name": "item_cooldown_20d",
        "cooldown_days": 20
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.ITEM_COOLDOWN
        self.cooldown_days = rule_config.get('cooldown_days', 20)

    def validate_config(self) -> bool:
        return self.cooldown_days >= 0

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        banned_by_date: Dict[dt.date, Set[str]] = filter_context.get('banned_by_date', {})
        banned = banned_by_date.get(date, set())
        if banned and len(pool) > 0:
            pool = pool[~pool['item'].isin(banned)]
        return pool

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool
