"""
Cooldown-style rules that prevent recent repetition.

* :class:`ItemCooldownMenuRule` — pre-filter: drop items used within
  the last N days (from :class:`HistoryManager` data).
* :class:`RiceBreadGapMenuRule` — pre-filter: drop rice-bread items
  on days where a recent rice-bread appearance triggers the gap.
* :class:`WeekSignatureCooldownMenuRule` — CP-SAT hard constraint:
  forbid exact re-use of a recent week's (date, slot → item) signature.

``_parse_signature_to_expected_map`` is re-exported at module scope so
tests can import it directly. The implementation lives on
:class:`HistoryManager` (single source of truth for signature parsing).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Set

import pandas as pd
from ortools.sat.python import cp_model

from ..history.history_manager import HistoryManager
from ..preprocessor.column_mapper import _norm_str
from src.constants import (
    BASE_SLOT_NAMES, REPEATABLE_SLOTS, COOLDOWN_EXEMPT_SLOTS, repeatable_row,
)
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnosticPhase,
    DiagnosticSeverity,
    DiagnoseContext,
    MenuRuleType,
    MenuRuleSeverity,
)
from .unique_items_menu_rule import matches_declared

# Re-export for tests / legacy callers; the canonical implementation is
# HistoryManager.parse_signature_to_expected_map.
_parse_signature_to_expected_map = HistoryManager.parse_signature_to_expected_map


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

    # Populated by diagnostics.run_diagnostics so diagnose() can read the
    # staple declarations its peers publish (`repeatable_item_flags`). Without
    # them diagnose() reports bans the solver does not apply — a 2-item bread
    # slot whose dishes are declared staples would be gated as an ERROR while
    # the solver happily serves them.
    _peer_rules: List[Any] = []

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.ITEM_COOLDOWN
        self.cooldown_days = rule_config.get('cooldown_days', 20)

    def validate_config(self) -> bool:
        return self.cooldown_days >= 0

    def _declared_repeatable(self) -> Dict[str, List[Any]]:
        """``{base_slot: [(include, exclude), ...]}`` from every peer rule."""
        out: Dict[str, List[Any]] = {}
        for rule in (self._peer_rules or ()):
            fn = getattr(rule, 'repeatable_item_flags', None)
            if not callable(fn):
                continue
            try:
                for slot, matcher in (fn() or {}).items():
                    out.setdefault(slot, []).append(matcher)
            except Exception:  # noqa: BLE001 — a bad peer must not break diagnose
                continue
        return out

    def _staple_mask(self, pool: pd.DataFrame, base_slot: str,
                     declared: Dict[str, Any]) -> pd.Series:
        """Rows the cooldown never bans: ontology-wide staples + declared ones."""
        return pool.apply(
            lambda row: (
                repeatable_row(row, base_slot)
                or matches_declared(row, base_slot, declared)
            ),
            axis=1,
        )

    def pre_filter_pool(self, pool: pd.DataFrame, date: dt.date,
                        base_slot: str, day_type: str,
                        filter_context: Dict[str, Any]) -> pd.DataFrame:
        # Repeatable slots (e.g. the plain-curd station) are never cooled down —
        # the same staple is meant to recur, so history bans don't apply.
        # COOLDOWN_EXEMPT_SLOTS (curd_side/curd_rice) are exempt from the ban too,
        # but KEEP unique_items: small condiment pools must not be drained empty
        # by the 20-day hard ban, yet should still vary within the week and only
        # repeat once every distinct dish is used (freshness rotates them).
        if base_slot in REPEATABLE_SLOTS or base_slot in COOLDOWN_EXEMPT_SLOTS:
            return pool
        banned_by_date: Dict[dt.date, Set[str]] = filter_context.get('banned_by_date', {})
        banned = banned_by_date.get(date, set())
        if not banned or len(pool) == 0:
            return pool
        # A staple item recurs by design, so the 20-day window never bans it
        # — same exemption the plain-curd slot gets above, applied per item
        # instead of per slot. Two sources, both honoured: the ontology-wide
        # flags in constants (the chicken kebab) and the per-city/per-client
        # `repeatable_items` declarations the solver collects (Pune's plain
        # chapati). Skipping the declared set would leave a "may repeat"
        # exemption that unique_items honours and the cooldown quietly
        # doesn't — which starves the slot a week later instead of now.
        declared = filter_context.get('extra_repeatable') or {}
        staple = self._staple_mask(pool, base_slot, declared)
        drop = pool['item'].isin(banned) & ~staple
        kept = pool[~drop]

        # Graceful degradation — the cooldown must NEVER empty a slot below the
        # number of dishes it needs that day, or a small pool turns the whole
        # solve INFEASIBLE (the failure that stopped counters sustaining a 10-
        # or 22-day run). If the ban would starve the slot, restore the least-
        # recently-served banned dishes (the ones closest to leaving the 20-day
        # window) — just enough to fill it. Freshness still prefers the freshest
        # candidate, so a dish only repeats early when the pool genuinely can't
        # avoid it. Same principle as unique_items' starved relaxation, and it
        # means the item cooldown can no longer make a plan INFEASIBLE.
        cfg = filter_context.get('cfg')
        needed = 1
        slot_counts = getattr(cfg, 'slot_counts', None) if cfg is not None else None
        if slot_counts:
            needed = max(1, int(slot_counts.get(base_slot, 1)))
        if len(kept) >= needed:
            return kept
        dropped = pool[drop]
        if len(dropped) == 0:
            return kept
        recency: Dict[str, int] = filter_context.get('recency_by_item') or {}
        # Oldest-served first: largest days-since-last-served, unknown = very old.
        rank = dropped['item'].map(lambda it: recency.get(_norm_str(it), 10 ** 6))
        dropped = dropped.assign(_cd_rank=rank.values).sort_values(
            '_cd_rank', ascending=False).drop(columns='_cd_rank')
        restore = dropped.head(needed - len(kept))
        return pd.concat([kept, restore])

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # All filtering happens in pre_filter_pool

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """For each (date, base_slot) the planner would visit, project
        the cooldown filter and report:

          - ERROR when the cooldown empties the pool — this is the
            chinese-starter case: 8 candidates, 8 banned, 0 remaining.
          - WARNING when the cooldown leaves the pool below the
            client's required slot count for that base slot.
          - (no diagnostic) when the cooldown leaves enough items.

        Doesn't apply the other rules' pre-filters (theme, ricebread
        gap) — those emit their own diagnostics. Keeping each rule
        scoped to its own constraint means the user sees N small,
        actionable messages instead of one big tangled one.
        """
        diags: List[Diagnostic] = []
        if not ctx.banned_by_date:
            return diags

        base_slots = ctx.active_base_slots or list(BASE_SLOT_NAMES)
        slot_counts = (
            ctx.client_cfg.slot_counts if ctx.client_cfg is not None else {}
        )
        # Same exemption the pre-filter applies, so the report and the solve
        # agree on which dishes the cooldown can actually take away.
        declared = self._declared_repeatable()
        staple_cache: Dict[str, Any] = {}

        for d in ctx.dates:
            banned = ctx.banned_by_date.get(d, set())
            if not banned:
                continue
            day_type = ctx.day_types.get(d, '')
            day_label = d.strftime('%A %d %b')

            for base in base_slots:
                if (d, base) in ctx.skip_cells:
                    continue
                if base in REPEATABLE_SLOTS or base in COOLDOWN_EXEMPT_SLOTS:
                    continue  # exempt from cooldown, so no cooldown diagnostic
                if base not in ctx.pools:
                    continue
                pool = ctx.pools[base]
                if len(pool) == 0 or 'item' not in pool.columns:
                    continue

                if base not in staple_cache:
                    staple_cache[base] = self._staple_mask(pool, base, declared)
                ban_mask = pool['item'].isin(banned) & ~staple_cache[base]
                ban_count = int(ban_mask.sum())
                if ban_count == 0:
                    continue
                remaining = len(pool) - ban_count
                count_needed = slot_counts.get(base, 1) if slot_counts else 1
                slot_label = base.replace('_', ' ')

                if remaining == 0:
                    # Not a blocker: pre_filter_pool restores the least-recently-
                    # served dishes so the slot is never actually starved (the
                    # cooldown can no longer make a plan INFEASIBLE). Report it as
                    # a WARNING so an operator still sees the pool is too small to
                    # honour the full 20-day window and a dish repeats early.
                    diags.append(Diagnostic(
                        rule=self.name,
                        rule_type=self.rule_type.value,
                        severity=DiagnosticSeverity.WARNING,
                        phase=DiagnosticPhase.PRE_FILTER,
                        message=(
                            f"Item cooldown ({self.cooldown_days} days) would ban "
                            f"all {ban_count} {slot_label} candidate"
                            f"{'s' if ban_count != 1 else ''} "
                            f"on {day_label} ({day_type or 'no theme'}); the "
                            f"cooldown is relaxed here so the slot still fills, "
                            f"and a recently-served {slot_label} repeats early."
                        ),
                        suggestion=(
                            f"Add more {slot_label} items to the ontology (or "
                            f"lower cooldown_days) if you want the full "
                            f"{self.cooldown_days}-day gap honoured for this slot."
                        ),
                        affected={
                            'date': d.isoformat(),
                            'slot': base,
                            'day_type': day_type,
                            'banned_count': ban_count,
                            'pool_size_before': len(pool),
                            'pool_size_after': remaining,
                            'cooldown_days': self.cooldown_days,
                        },
                    ))
                elif remaining < count_needed:
                    diags.append(Diagnostic(
                        rule=self.name,
                        rule_type=self.rule_type.value,
                        severity=DiagnosticSeverity.WARNING,
                        phase=DiagnosticPhase.PRE_FILTER,
                        message=(
                            f"Item cooldown banned {ban_count}/{len(pool)} "
                            f"{slot_label} candidates on {day_label}; "
                            f"{remaining} left but the slot needs "
                            f"{count_needed}."
                        ),
                        suggestion=(
                            f"Add more {slot_label} items or relax the "
                            f"cooldown so at least {count_needed} candidates "
                            f"are available for this date."
                        ),
                        affected={
                            'date': d.isoformat(),
                            'slot': base,
                            'day_type': day_type,
                            'banned_count': ban_count,
                            'pool_size_before': len(pool),
                            'pool_size_after': remaining,
                            'count_needed': count_needed,
                            'cooldown_days': self.cooldown_days,
                        },
                    ))
        return diags


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

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """For each date with ``ricebread_ban_day[date] == True``,
        project the bread-pool filter (drop ``is_rice_bread == 1``)
        and emit:

          - ERROR if bread pool becomes empty after the ban.
          - INFO  if the ban removed items but the pool is still OK.

        The bread slot is the only slot this rule touches, so we
        scope the diagnostic to it.
        """
        diags: List[Diagnostic] = []
        if not ctx.ricebread_ban_day:
            return diags
        bread = ctx.pools.get('bread')
        if bread is None or len(bread) == 0:
            return diags
        if 'is_rice_bread' not in bread.columns:
            return diags

        rb_mask = bread['is_rice_bread'] == 1
        rb_total = int(rb_mask.sum())
        non_rb_total = int((~rb_mask).sum())

        for d, banned_today in ctx.ricebread_ban_day.items():
            if not banned_today:
                continue
            if (d, 'bread') in ctx.skip_cells:
                continue
            day_label = d.strftime('%A %d %b')

            if non_rb_total == 0:
                diags.append(Diagnostic(
                    rule=self.name,
                    rule_type=self.rule_type.value,
                    severity=DiagnosticSeverity.ERROR,
                    phase=DiagnosticPhase.PRE_FILTER,
                    message=(
                        f"Rice-bread gap ({self.gap_days} days) bans rice-bread "
                        f"items on {day_label}, but the bread pool only has "
                        f"rice-bread items ({rb_total}). Nothing left to pick."
                    ),
                    suggestion=(
                        "Add at least one non-rice-bread item to the bread "
                        "pool, or reduce the rice-bread gap so this date is "
                        "outside the window."
                    ),
                    affected={
                        'date': d.isoformat(),
                        'slot': 'bread',
                        'gap_days': self.gap_days,
                        'rice_bread_count': rb_total,
                        'non_rice_bread_count': non_rb_total,
                    },
                ))
            elif rb_total > 0:
                diags.append(Diagnostic(
                    rule=self.name,
                    rule_type=self.rule_type.value,
                    severity=DiagnosticSeverity.INFO,
                    phase=DiagnosticPhase.PRE_FILTER,
                    message=(
                        f"Rice-bread gap bans {rb_total} rice-bread items from "
                        f"the bread pool on {day_label}; {non_rb_total} "
                        f"non-rice-bread items remain."
                    ),
                    suggestion="No action needed — pool is still healthy.",
                    affected={
                        'date': d.isoformat(),
                        'slot': 'bread',
                        'gap_days': self.gap_days,
                        'rice_bread_count': rb_total,
                        'non_rice_bread_count': non_rb_total,
                    },
                ))
        return diags


# ---------------------------------------------------------------------------
# WeekSignatureCooldownMenuRule
# ---------------------------------------------------------------------------


class WeekSignatureCooldownMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "week_signature_cooldown",
        "name": "no_repeat_weeks",
        "cooldown_days": 30
    }
    """

    severity = MenuRuleSeverity.SOFT

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
