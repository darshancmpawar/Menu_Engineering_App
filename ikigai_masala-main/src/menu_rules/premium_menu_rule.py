"""
Premium menu rule: max 1 premium item per day, 1-2 per week.
"""

from typing import Dict, Any
from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


class PremiumMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "premium",
        "name": "premium_limits",
        "max_per_day": 1,
        "min_per_horizon": 1,
        "max_per_horizon": 2
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.PREMIUM
        self.max_per_day = rule_config.get('max_per_day', 1)
        self.min_per_horizon = rule_config.get('min_per_horizon', 1)
        self.max_per_horizon = rule_config.get('max_per_horizon', 2)

    def validate_config(self) -> bool:
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cfg = context.get('cfg')
        dates = context.get('dates', [])
        day_premium_vars = context.get('day_premium_vars', {})

        if not cfg or not cfg.premium_flag_col:
            return

        premium_day_bools = []
        for di in range(len(dates)):
            lits = day_premium_vars.get(di, [])
            prem_day = model.NewBoolVar(f'premium_day_{di}')
            if lits:
                model.Add(sum(lits) <= self.max_per_day)
                model.Add(sum(lits) == prem_day)
            else:
                model.Add(prem_day == 0)
            premium_day_bools.append(prem_day)

        total = sum(premium_day_bools)
        has_any = any(len(day_premium_vars.get(di, [])) > 0 for di in range(len(dates)))
        if has_any:
            model.Add(total >= self.min_per_horizon)
            model.Add(total <= self.max_per_horizon)
        else:
            model.Add(total == 0)
