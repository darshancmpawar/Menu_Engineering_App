"""
Cooldown-style rules that prevent recent repetition.

* :class:`ItemCooldownMenuRule` — pre-filter: drop items used within
  the last N days (from :class:`HistoryManager` data).
* :class:`RiceBreadGapMenuRule` — pre-filter: drop rice-bread items
  on days where a recent rice-bread appearance triggers the gap.
* :class:`WeekSignatureCooldownMenuRule` — CP-SAT hard constraint:
  forbid exact re-use of a recent week's (date, slot → item) signature.

``_parse_signature_to_expected_map`` is exposed at module scope so
tests can import it directly.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, Set

import pandas as pd
from ortools.sat.python import cp_model

from ..preprocessor.column_mapper import _norm_str
from .base_menu_rule import BaseMenuRule, MenuRuleType


# ---------------------------------------------------------------------------
# ItemCooldownMenuRule
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# RiceBreadGapMenuRule
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# WeekSignatureCooldownMenuRule
# ---------------------------------------------------------------------------


def _parse_signature_to_expected_map(sig: str) -> Dict:
    parts = sig.split('|')
    out = {}
    i = 0
    while i < len(parts):
        token = parts[i]
        if re.match(r'^\d{4}-\d{2}-\d{2}$', token):
            date_iso = token
            i += 1
            while i < len(parts) and not re.match(r'^\d{4}-\d{2}-\d{2}$', parts[i]):
                kv = parts[i]
                if '=' in kv:
                    slot, val = kv.split('=', 1)
                    out[(date_iso, _norm_str(slot))] = _norm_str(val)
                i += 1
        else:
            i += 1
    return out


class WeekSignatureCooldownMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "week_signature_cooldown",
        "name": "no_repeat_weeks",
        "cooldown_days": 30
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.WEEK_SIGNATURE_COOLDOWN
        self.cooldown_days = rule_config.get('cooldown_days', 30)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        recent_sigs = context.get('recent_sigs', set())

        for sig in recent_sigs:
            exp = _parse_signature_to_expected_map(sig)
            lits = []
            for cell in cells:
                want = exp.get((cell.date.isoformat(), _norm_str(cell.slot_id)))
                if not want:
                    lits = []
                    break
                found = None
                for var, row in zip(cell.x_vars, cell.cand_rows):
                    if _norm_str(row.get('item', '')) == want:
                        found = var
                        break
                if found is None:
                    lits = []
                    break
                lits.append(found)
            if lits and len(lits) >= 2:
                model.Add(sum(lits) <= len(lits) - 1)
