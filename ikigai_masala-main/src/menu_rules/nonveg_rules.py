"""
Non-veg menu rules.

* :class:`NonvegBiryaniWeeklyRule` — CP-SAT cap: at most N nonveg
  biryani days across the week.
* :class:`NonvegDryPreferenceRule` — pre-filter: for nonveg_main slot
  2+, prefer dry items; fall back to gravy; on biryani/chinese days
  exclude the theme items (those go in slot 1) first.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List

import pandas as pd
from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)

from ..preprocessor.column_mapper import _to_bool01
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnosticPhase,
    DiagnosticSeverity,
    DiagnoseContext,
    MenuRuleType,
)


# ---------------------------------------------------------------------------
# NonvegBiryaniWeeklyRule
# ---------------------------------------------------------------------------


class NonvegBiryaniWeeklyRule(BaseMenuRule):
    """
    Config:
    {
        "type": "nonveg_biryani_weekly",
        "name": "nonveg_biryani_once_per_week",
        "max_per_week": 1
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.NONVEG_BIRYANI_WEEKLY
        self.max_per_week = int(rule_config.get('max_per_week', 1))

    def validate_config(self) -> bool:
        return self.max_per_week >= 0

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')

        if not cells or not link_any:
            return

        biryani_day_vars = []

        for di in range(len(dates)):
            nv_cells = [c for c in cells if c.d_idx == di and c.base_slot == 'nonveg_main']
            if not nv_cells:
                continue

            biryani_lits = [
                v for c in nv_cells
                for v, r in zip(c.x_vars, c.cand_rows)
                if int(r.get('is_nonveg_biryani', 0)) == 1
            ]

            if biryani_lits:
                day_has_biryani = model.NewBoolVar(f'nonveg_biryani_day_{di}')
                link_any(model, biryani_lits, day_has_biryani)
                biryani_day_vars.append(day_has_biryani)

        if not biryani_day_vars:
            return

        # The cap is enforced as configured. It is NOT auto-raised to fit a
        # theme map that forces more biryani days than the cap allows: that
        # combination is a configuration conflict, and silently raising the cap
        # would hand back a menu that breaks the weekly-variety rule the cap
        # exists to enforce. ``diagnose()`` reports the conflict with the exact
        # config change to make (disable this rule for the counter, or raise
        # max_per_week) so the relaxation is a decision someone takes, not one
        # the solver takes for them.
        model.Add(sum(biryani_day_vars) <= self.max_per_week)

    def forced_biryani_days(self, ctx: DiagnoseContext) -> int:
        """Days whose nonveg_main pool offers nothing but nonveg biryani.

        On a biryani-theme day the theme filter narrows a single-nonveg counter
        to biryani only, so a biryani is unavoidable on that day. More such days
        than ``max_per_week`` is provably unsatisfiable.
        """
        pool = ctx.pools.get('nonveg_main')
        if pool is None or 'is_nonveg_biryani' not in pool.columns:
            return 0
        active = ctx.active_base_slots
        if active is not None and 'nonveg_main' not in active:
            return 0

        forced = 0
        for d in ctx.dates:
            if (d, 'nonveg_main') in (ctx.skip_cells or set()):
                continue
            day_pool = pool
            day_type = ctx.day_types.get(d, '')
            filter_ctx = {
                'cfg': ctx.cfg, 'banned_by_date': {}, 'ricebread_ban_day': {},
                'pools': ctx.pools, 'slot_num': None,
            }
            for rule in (getattr(self, '_peer_rules', None) or []):
                day_pool = rule.pre_filter_pool(
                    day_pool, d, 'nonveg_main', day_type, filter_ctx)
            if len(day_pool) and all(
                _to_bool01(v) == 1
                for v in day_pool['is_nonveg_biryani'].tolist()
            ):
                forced += 1

        # A biryani is also unavoidable on a day whose slot_composition mandates
        # one — the pool is not biryani-only there (the pair's other half is a
        # gravy), so the check above misses it. Siemens Technology's non-veg
        # counter has two biryani-theme days against this cap of one and used to
        # come back as a bare INFEASIBLE.
        from .slot_composition_rule import days_forced_by_composition
        by_composition = days_forced_by_composition(
            getattr(self, '_peer_rules', None), ctx, 'nonveg_main',
            lambda r: _to_bool01(r.get('is_nonveg_biryani', 0)) == 1,
        )
        return max(forced, by_composition)

    # Populated by the diagnostics aggregator so the check above can replay the
    # theme filter that narrows the pool.
    _peer_rules: List[Any] = []

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Constraint is ``sum(nonveg_biryani_day_vars) <= max_per_week``.

        Emits INFO when the constraint is a no-op (no
        ``is_nonveg_biryani=1`` items anywhere) so users can see why
        their cap isn't doing anything, and WARNING when the rule is
        on but no nonveg_main slot exists in any pool / skip_cells
        zeroes it out entirely.
        """
        diags: List[Diagnostic] = []
        pool = ctx.pools.get('nonveg_main')
        if pool is None:
            return diags
        if 'is_nonveg_biryani' not in pool.columns:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"Nonveg biryani weekly cap is set "
                    f"(max_per_week={self.max_per_week}) but the "
                    f"'is_nonveg_biryani' column is missing from the "
                    f"nonveg_main pool. The constraint is a no-op."
                ),
                suggestion=(
                    "Populate the is_nonveg_biryani flag column in the "
                    "ontology Excel, or remove this rule."
                ),
                affected={'max_per_week': self.max_per_week},
            ))
            return diags
        biryani_count = int(
            pool['is_nonveg_biryani'].fillna(0).astype(int).eq(1).sum()
        )
        if biryani_count == 0:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    "Nonveg biryani weekly cap is set but the "
                    "nonveg_main pool has 0 items with "
                    "is_nonveg_biryani=1. The constraint is a no-op."
                ),
                suggestion="No action needed unless you expected biryani items.",
                affected={
                    'max_per_week': self.max_per_week,
                    'biryani_count': 0,
                },
            ))
            return diags

        # Config conflict: the theme map forces a nonveg biryani on more days
        # than the cap permits. Provably unsatisfiable, so report it as an ERROR
        # (which gates /plan with an actionable 422) rather than letting the
        # solver return a bare INFEASIBLE — or, worse, quietly raising the cap.
        forced = self.forced_biryani_days(ctx)
        if forced > self.max_per_week:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.ERROR,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"This counter's themes leave nonveg biryani as the only "
                    f"option on {forced} day(s), but the weekly cap allows "
                    f"{self.max_per_week}. Those rules contradict each other, "
                    f"so no menu can satisfy both."
                ),
                suggestion=(
                    f"For a counter that is meant to serve biryani daily, add "
                    f"\"{self.name}\" to this client's `disable` list in "
                    f"client_rules.json (that is the intended way to say \"the "
                    f"weekly cap does not apply here\"), or raise max_per_week "
                    f"to {forced}. Alternatively give the counter non-biryani "
                    f"theme days, or a second nonveg_main slot so a "
                    f"non-biryani dish can share the day."
                ),
                affected={
                    'max_per_week': self.max_per_week,
                    'forced_biryani_days': forced,
                },
            ))
        return diags


# ---------------------------------------------------------------------------
# NonvegDryPreferenceRule
# ---------------------------------------------------------------------------


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

        # Prefer dry items — reads the column populated by ColumnMapper.apply()
        # rather than re-running the heuristic per row.
        if 'is_nonveg_dry' in pool.columns:
            dry_pool = pool[pool['is_nonveg_dry'].map(_to_bool01) == 1]
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
