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
        """``{base_slot: [(include, exclude), ...]}`` from every peer rule.

        BOTH declarations, because both exempt a dish from the ban: the staples
        (``repeatable_item_flags``) and the cooldown-only set
        (``cooldown_exempt_item_flags``, which keeps ``unique_items``). Reading
        only the first would report bans the solver does not apply.
        """
        out: Dict[str, List[Any]] = {}
        for rule in (self._peer_rules or ()):
            for hook in ('repeatable_item_flags', 'cooldown_exempt_item_flags'):
                fn = getattr(rule, hook, None)
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
        # Two declarations, both exempting from the ban: the staples (also
        # exempt from unique_items) and the cooldown-only set, which keeps
        # unique_items so the slot still varies within a plan — the per-client
        # form of COOLDOWN_EXEMPT_SLOTS above.
        declared = {**(filter_context.get('extra_repeatable') or {})}
        for slot, matchers in (filter_context.get('extra_cooldown_exempt')
                               or {}).items():
            declared[slot] = list(declared.get(slot, ())) + list(matchers)
        staple = self._staple_mask(pool, base_slot, declared)
        # No-repeat is HARD. A cooled-down dish is removed outright and the rule
        # never "borrows back" a recent dish to fill a gap: repetition is allowed
        # only for the slots that declare it (REPEATABLE_SLOTS /
        # COOLDOWN_EXEMPT_SLOTS above) or for a dish declared a staple. If that
        # empties a slot, the answer is more dishes in the ontology for that
        # category — not a quietly repeated menu.
        drop = pool['item'].isin(banned) & ~staple
        return pool[~drop]

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
                    # A real blocker: no-repeat is hard, so an emptied pool has
                    # nothing left to serve and the solve is INFEASIBLE. The fix
                    # is more dishes in this category for this city.
                    diags.append(Diagnostic(
                        rule=self.name,
                        rule_type=self.rule_type.value,
                        severity=DiagnosticSeverity.ERROR,
                        phase=DiagnosticPhase.PRE_FILTER,
                        message=(
                            f"Item cooldown ({self.cooldown_days} days) banned "
                            f"all {ban_count} {slot_label} candidate"
                            f"{'s' if ban_count != 1 else ''} "
                            f"on {day_label} ({day_type or 'no theme'}). "
                            f"Pool is empty after cooldown."
                        ),
                        suggestion=(
                            f"Add more {slot_label} items to this city's "
                            f"ontology (a slot needs roughly one dish per "
                            f"working day in the {self.cooldown_days}-day "
                            f"window), or lower cooldown_days for this rule."
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
