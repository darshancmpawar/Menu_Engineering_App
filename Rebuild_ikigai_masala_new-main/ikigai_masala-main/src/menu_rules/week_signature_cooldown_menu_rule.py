"""
Week signature cooldown rule: prevent exact duplication of past week plans.

CP-SAT constraint: for each recent signature, sum(matching_vars) <= N-1.
"""

import re
from typing import Dict, Any
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType
from ..preprocessor.column_mapper import _norm_str


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

    def validate_config(self) -> bool:
        return True

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
