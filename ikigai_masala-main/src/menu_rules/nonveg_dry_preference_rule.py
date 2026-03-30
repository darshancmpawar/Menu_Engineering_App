"""
Nonveg dry preference rule: for nonveg_main slot 2+, prefer dry items.

Pre-filter phase rule — narrows pool to dry nonveg items when available.
On biryani/chinese days, excludes biryani/chinese items from slot 2+
(those belong in slot 1) and then prefers dry items.
"""

import datetime as dt
import pandas as pd
from typing import Dict, Any, Set

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType
from ..preprocessor.column_mapper import _to_bool01, _is_nonveg_dry_row


class NonvegDryPreferenceRule(BaseMenuRule):
    """
    Config:
    {
        "type": "nonveg_dry_preference",
        "name": "prefer_nonveg_dry_slot2"
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.NONVEG_DRY_PREFERENCE

    def validate_config(self) -> bool:
        return True

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        # Only applies to nonveg_main slots numbered 2+ (slot_num >= 2)
        slot_num = filter_context.get('slot_num')
        if base_slot != 'nonveg_main' or not slot_num or slot_num < 2:
            return pool
        if len(pool) == 0:
            return pool

        cfg = filter_context.get('cfg')
        banned = filter_context.get('banned_by_date', {}).get(date, set())
        pools = filter_context.get('pools', {})

        # On biryani/chinese days: use full nonveg pool minus biryani/chinese items
        if day_type in ('biryani', 'chinese') and 'nonveg_main' in pools:
            alt_pool = pools['nonveg_main'].copy()
            if cfg:
                if cfg.f_chinese_nonveg and cfg.f_chinese_nonveg in alt_pool.columns:
                    alt_pool = alt_pool[alt_pool[cfg.f_chinese_nonveg].map(_to_bool01) == 0]
                if cfg.f_nonveg_biryani and cfg.f_nonveg_biryani in alt_pool.columns:
                    alt_pool = alt_pool[alt_pool[cfg.f_nonveg_biryani].map(_to_bool01) == 0]
            if banned:
                alt_pool = alt_pool[~alt_pool['item'].isin(banned)]
            if len(alt_pool) > 0:
                pool = alt_pool

        # Prefer dry items
        dry_pool = pool[pool.apply(_is_nonveg_dry_row, axis=1)]
        if len(dry_pool) > 0:
            return dry_pool

        # Fallback: prefer gravy items
        if 'is_nonveg_gravy' in pool.columns:
            gravy_pool = pool[pool['is_nonveg_gravy'].map(_to_bool01) == 1]
            if len(gravy_pool) > 0:
                return gravy_pool

        return pool

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool
