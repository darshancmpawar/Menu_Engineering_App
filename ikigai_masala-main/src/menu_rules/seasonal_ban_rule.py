"""Seasonal high-risk vegetables, per date.

Built by ``src.application.solve_inputs`` for every plan whose city has a
seasonal list, with the list resolved per date so a plan that crosses a month
end uses each month's own list::

    {"type": "seasonal_ban", "name": "seasonal_vegetables", "priority": "medium",
     "by_date": {"2026-10-30": {"month": "2026-10", "red": [...], "yellow": [...],
                                "salad_bans": ["tomato"]}, ...}}

What it does, and why each part sits where it does:

* **Red list: hard.** Removed in ``pre_filter_pool``, before the solver sees a
  candidate, exactly like ``ingredient_ban``. Red means "completely avoided".
* **Salad bans: hard, salad slot only.** "Do not use tomatoes in the salad"
  bans tomato dishes from the salad slot and nowhere else.
* **Pinned dishes stay.** A client pin (``cfg.forced_items``) is never removed:
  the kitchen makes it without the vegetable, and the planner's seasonal panel
  tells them so. Removing it would silently drop the pin, because the solver
  only narrows a cell to a pin that survived the pre-filters.
* **Yellow list: soft.** One penalty per yellow dish chosen, at the rule's
  priority (medium by default): the solver steers away but can still use one
  when a slot would otherwise run thin.
* **Mixed-vegetable dishes are not touched**: their contents are unknown, and
  the kitchen leaves the red-list vegetables out (a product decision).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Set

import pandas as pd
from ortools.sat.python import cp_model

from ..constants import BASE_SLOT_NAMES, OBJECTIVE_TIER_WEIGHTS
from ..seasonal.bans import default_matcher, vegetable_label
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnosticPhase,
    DiagnosticSeverity,
    DiagnoseContext,
    MenuRuleType,
)

# Below this many dishes left in a slot for a month, pre-flight warns.
THIN_POOL = 5


class SeasonalBanRule(BaseMenuRule):

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SEASONAL_BAN
        self.by_date: Dict[str, Dict[str, Any]] = {}
        for iso, lists in (rule_config.get('by_date') or {}).items():
            if not isinstance(lists, dict):
                continue
            self.by_date[str(iso)] = {
                'month': lists.get('month', str(iso)[:7]),
                'red': sorted({str(v) for v in lists.get('red') or []}),
                'yellow': sorted({str(v) for v in lists.get('yellow') or []}),
                'salad_bans': sorted({str(v) for v in lists.get('salad_bans') or []}),
            }
        prio = str(rule_config.get('priority', 'medium')).lower()
        self.weight = OBJECTIVE_TIER_WEIGHTS.get(prio, OBJECTIVE_TIER_WEIGHTS['medium'])
        self.matcher = default_matcher()

    def validate_config(self) -> bool:
        return bool(self.by_date)

    # --- helpers -----------------------------------------------------------

    def _lists(self, date: dt.date) -> Dict[str, Any]:
        return self.by_date.get(date.isoformat()) or {}

    @staticmethod
    def _pinned_names(filter_context: Dict[str, Any], date: dt.date, base_slot: str) -> Set[str]:
        cfg = (filter_context or {}).get('cfg')
        forced = getattr(cfg, 'forced_items', None) or {}
        out = set()
        for (d, slot_id), name in forced.items():
            if d == date and str(slot_id).split('__')[0] == base_slot and name:
                out.add(str(name).strip().lower())
        return out

    def hard_mask(self, pool: pd.DataFrame, lists: Dict[str, Any], base_slot: str) -> pd.Series:
        """Rows the red list (and, in the salad slot, the salad bans) removes."""
        mask = self.matcher.mask(pool, lists.get('red') or [])
        if base_slot == 'salad' and lists.get('salad_bans'):
            mask |= self.matcher.mask(pool, lists['salad_bans'])
        return mask

    # --- the rule --------------------------------------------------------------

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        lists = self._lists(date)
        if len(pool) == 0 or not lists or not (lists['red'] or lists['salad_bans']):
            return pool
        mask = self.hard_mask(pool, lists, base_slot)
        pinned = self._pinned_names(filter_context, date, base_slot)
        if pinned and 'item' in pool.columns:
            mask &= ~pool['item'].astype(str).str.strip().str.lower().isin(pinned)
        return pool[~mask]

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass

    def get_objective_terms(self, model: cp_model.CpModel,
                            context: Dict[str, Any]) -> List:
        """One penalty per yellow-list dish chosen."""
        hits = []
        for cell in context.get('cells', []) or []:
            yellow = self._lists(cell.date).get('yellow') or []
            if not yellow:
                continue
            for row, var in zip(cell.cand_rows, cell.x_vars):
                if self.matcher.vegetables_in(row.get('item'), row.get('key_ingredient'),
                                              yellow, row.get('is_leafy_based_dish')):
                    hits.append(var)
        return [sum(hits) * (-abs(self.weight))] if hits else []

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Per month and slot: empty is an error, thin is a warning."""
        diags: List[Diagnostic] = []
        months: Dict[str, Dict[str, Any]] = {}
        for d in ctx.dates:
            lists = self._lists(d)
            if lists and (lists['red'] or lists['salad_bans']):
                months.setdefault(lists['month'], lists)
        base_slots = ctx.active_base_slots or list(BASE_SLOT_NAMES)
        for month, lists in months.items():
            red_labels = ', '.join(vegetable_label(v) for v in lists['red'])
            for base in base_slots:
                pool = ctx.pools.get(base)
                if pool is None or len(pool) == 0:
                    continue
                removed = int(self.hard_mask(pool, lists, base).sum())
                if not removed:
                    continue
                left = len(pool) - removed
                slot = base.replace('_', ' ')
                if left == 0:
                    severity, msg = DiagnosticSeverity.ERROR, (
                        f'The {month} high-risk vegetable list ({red_labels}) removes every '
                        f'{slot} dish ({removed}). The slot cannot be filled.')
                elif left < THIN_POOL:
                    severity, msg = DiagnosticSeverity.WARNING, (
                        f'The {month} high-risk vegetable list leaves only {left} {slot} '
                        f'dish(es) after removing {removed}.')
                else:
                    severity, msg = DiagnosticSeverity.INFO, (
                        f'The {month} high-risk vegetable list removes {removed} of '
                        f'{len(pool)} {slot} dishes; {left} remain.')
                diags.append(Diagnostic(
                    rule=self.name, rule_type=self.rule_type.value, severity=severity,
                    phase=DiagnosticPhase.PRE_FILTER, message=msg,
                    suggestion=('Add dishes without these vegetables to this slot, or review '
                                'the seasonal list for the month.') if left < THIN_POOL else None,
                    affected={'slot': base, 'month': month, 'red': lists['red'],
                              'removed': removed, 'pool_size_before': len(pool),
                              'pool_size_after': left},
                ))
        return diags
