"""
Theme slot filter rule: enforce theme-based pool filtering.

Replicates the old app's ``enforce_day_slot_filters_static()`` logic:
- **Chinese days**: rice → Chinese fried rice, veg_gravy → Chinese veg gravy,
  nonveg_main → Chinese chicken gravy, starter → Chinese starter,
  veg_dry → Chinese side.
- **Biryani days**: rice → veg biryani, nonveg_main → nonveg biryani.
- **South/North days**: non-exempt slots → matching cuisine_family.
- **Bread cuisine lock**: bread is south-Indian only on south days.

Pre-filter phase rule.
"""

import datetime as dt
import pandas as pd
from typing import Dict, Any, Set

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType
from src.constants import EXEMPT_FROM_CUISINE
from ..preprocessor.column_mapper import _norm_str, _to_bool01


# Slots that get Chinese-specific filtering
_CHINESE_FLAG_MAP = {
    'rice': 'is_chinese_fried_rice',
    'veg_gravy': 'is_chinese_veg_gravy',
    'nonveg_main': 'is_chinese_chicken_gravy',
}

# Biryani flag map
_BIRYANI_FLAG_MAP = {
    'rice': 'is_mixedveg_biryani',
    'nonveg_main': 'is_nonveg_biryani',
}


def _chinese_side_mask(pool: pd.DataFrame) -> pd.Series:
    """Detect Chinese-appropriate veg_dry items via text heuristics."""
    text = (pool['item'].astype(str) + ' ' +
            pool.get('sub_category', pd.Series('', index=pool.index)).astype(str))
    text = text.str.lower()
    return (
        text.str.contains('chinese', na=False) |
        text.str.contains('manchurian', na=False) |
        text.str.contains('schezwan', na=False) |
        text.str.contains('szechuan', na=False) |
        text.str.contains('gobi_65', na=False) |
        text.str.contains('gobi 65', na=False) |
        text.str.contains('baby_corn', na=False) |
        text.str.contains('baby corn', na=False) |
        text.str.contains('noodle', na=False) |
        text.str.contains('chilli', na=False)
    )


class ThemeSlotFilterRule(BaseMenuRule):
    """
    Config:
    {
        "type": "theme_slot_filter",
        "name": "theme_cuisine_filter",
        "exempt_slots": ["welcome_drink", "dal", "sambar", "rasam",
                         "starter", "soup", "salad", "healthy_rice"]
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.THEME_SLOT_FILTER
        exempt = rule_config.get('exempt_slots')
        self.exempt_slots: Set[str] = set(exempt) if exempt else set(EXEMPT_FROM_CUISINE)

    def validate_config(self) -> bool:
        return True

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        if len(pool) == 0:
            return pool

        cfg = filter_context.get('cfg')

        if day_type == 'chinese':
            return self._filter_chinese(pool, base_slot, cfg)
        if day_type == 'biryani':
            return self._filter_biryani(pool, base_slot, cfg)
        if day_type in ('south', 'north'):
            return self._filter_cuisine(pool, base_slot, day_type, cfg)
        # 'mix', 'holiday', 'normal' — no theme filtering
        return pool

    def _filter_chinese(self, pool: pd.DataFrame, base_slot: str, cfg) -> pd.DataFrame:
        flag_col = _CHINESE_FLAG_MAP.get(base_slot)
        if flag_col and flag_col in pool.columns:
            filtered = pool[pool[flag_col].map(_to_bool01) == 1]
            if len(filtered) > 0:
                return filtered

        if base_slot == 'veg_dry':
            mask = _chinese_side_mask(pool)
            filtered = pool[mask]
            if len(filtered) > 0:
                return filtered

        # Exempt slots and slots without flags: return unfiltered
        return pool

    def _filter_biryani(self, pool: pd.DataFrame, base_slot: str, cfg) -> pd.DataFrame:
        flag_col = _BIRYANI_FLAG_MAP.get(base_slot)
        if flag_col and flag_col in pool.columns:
            filtered = pool[pool[flag_col].map(_to_bool01) == 1]
            if len(filtered) > 0:
                return filtered
        return pool

    def _filter_cuisine(self, pool: pd.DataFrame, base_slot: str,
                        day_type: str, cfg) -> pd.DataFrame:
        cuisine_col = cfg.cuisine_col if cfg else 'cuisine_family'
        south_val = cfg.cuisine_south_value if cfg else 'south_indian'
        north_val = cfg.cuisine_north_value if cfg else 'north_indian'

        target = south_val if day_type == 'south' else north_val

        # Bread cuisine lock: south bread on south days, non-south on others
        if base_slot == 'bread':
            if cuisine_col in pool.columns:
                if day_type == 'south':
                    filtered = pool[pool[cuisine_col].map(_norm_str) == south_val]
                else:
                    filtered = pool[pool[cuisine_col].map(_norm_str) != south_val]
                if len(filtered) > 0:
                    return filtered
            return pool

        # Exempt slots: no cuisine filtering
        if base_slot in self.exempt_slots:
            return pool

        # Non-exempt slots: filter by matching cuisine_family
        if cuisine_col in pool.columns:
            filtered = pool[pool[cuisine_col].map(_norm_str) == target]
            if len(filtered) > 0:
                return filtered

        return pool

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool
