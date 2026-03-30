"""
Rice-bread gap rule: ban rice-bread items if used within the last N days.

Pre-filter phase rule — removes rice-bread candidates from bread pool.
"""

import datetime as dt
import pandas as pd
from typing import Dict, Any

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class RiceBreadGapMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "ricebread_gap",
        "name": "ricebread_gap_10d",
        "gap_days": 10
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.RICEBREAD_GAP
        self.gap_days = rule_config.get('gap_days', 10)

    def validate_config(self) -> bool:
        return self.gap_days >= 0

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        if base_slot != 'bread':
            return pool
        ricebread_ban_day = filter_context.get('ricebread_ban_day', {})
        if ricebread_ban_day.get(date, False) and 'is_rice_bread' in pool.columns:
            pool = pool[pool['is_rice_bread'] == 0]
        return pool

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool
