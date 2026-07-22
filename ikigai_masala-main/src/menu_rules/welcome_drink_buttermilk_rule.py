"""Welcome-drink buttermilk rule.

Force the welcome-drink slot to be buttermilk on exactly ``count`` days of the
horizon (default 2). The solver chooses *which* days; when ``non_consecutive``
is set (default) the chosen days may not be adjacent.

Buttermilk items are identified by the ``is_buttermilk`` flag on the ontology
(populated for the regional buttermilk drinks — chaas / majjige / neer mor /
spiced buttermilk, etc.).
"""

from typing import Dict, Any, List

from ortools.sat.python import cp_model

from .base_menu_rule import BaseMenuRule, MenuRuleType


class WelcomeDrinkButtermilkRule(BaseMenuRule):
    """
    Config:
    {
        "type": "welcome_drink_buttermilk",
        "name": "buttermilk_twice_weekly",
        "count": 2,
        "non_consecutive": true
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.WELCOME_DRINK_BUTTERMILK
        self.count = int(rule_config.get('count', 2))
        self.non_consecutive = bool(rule_config.get('non_consecutive', True))
        self.flag = rule_config.get('flag', 'is_buttermilk')
        self.base_slot = rule_config.get('base_slot', 'welcome_drink')

    def validate_config(self) -> bool:
        return self.count >= 0

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        find_cells = context.get('find_cells_fn')
        link_any = context.get('link_any_fn')

        if not cells or not find_cells or not link_any or self.count <= 0:
            return

        # One "is this day's welcome drink buttermilk?" bool per day that has a
        # welcome-drink cell. link_any forces it to 0 when the day has no
        # buttermilk candidate at all.
        bm_by_day: List = []  # (day_index, bool_var)
        for di, _ in enumerate(dates):
            wd_cells = find_cells(cells, di, self.base_slot)
            if not wd_cells:
                continue
            lits = [
                v
                for c in wd_cells
                for v, row in zip(c.x_vars, c.cand_rows)
                if int(row.get(self.flag, 0)) == 1
            ]
            b = model.NewBoolVar(f'buttermilk_day_{di}')
            link_any(model, lits, b)
            bm_by_day.append((di, b))

        if not bm_by_day:
            return

        n = len(bm_by_day)
        # Cap the target to what the horizon can actually host so a short week
        # (or a weekend-only plan) relaxes gracefully instead of going
        # INFEASIBLE. With non-consecutive placement, at most ceil(n/2) days
        # can carry buttermilk.
        target = min(self.count, (n + 1) // 2 if self.non_consecutive else n)
        if target <= 0:
            return

        bvars = [b for _, b in bm_by_day]
        model.Add(sum(bvars) == target)

        if self.non_consecutive:
            for (di_a, ba), (di_b, bb) in zip(bm_by_day, bm_by_day[1:]):
                if di_b == di_a + 1:  # genuinely adjacent calendar days
                    model.Add(ba + bb <= 1)
