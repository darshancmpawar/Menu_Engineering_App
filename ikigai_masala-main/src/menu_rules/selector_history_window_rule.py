"""Cross-week cadence: a selector may recur only once per rolling window.

Some rules span longer than a single plan — "fish once every 15 days", "a
sambar once a fortnight", "oil-based bread monthly". A single 5-day solve
cannot see the previous weeks, so these can only be enforced by reading saved
history: look back ``window_days`` from each planned date and, if any dish
matching the selector was served inside that window, ban the whole selector on
that date.

This is the selector-level twin of the per-dish item cooldown. The cooldown
bans a *specific dish* for `item_cooldown_days`; this bans a *category / flag*
(any fish, any biryani, any kofta) for its own `window_days`. The ban is
computed upstream (`api.app`, which has the ontology frame and the history) and
folded into the same ``banned_by_date`` the item-cooldown pre-filter already
applies — so there is no new solver machinery, and a banned selector simply has
no candidate on those dates.

The rule pairs with a within-plan cap (`selector_frequency` `max`/`daily_max`):
this rule stops the selector recurring *across* plans, the cap stops it
recurring *within* one. For windows longer than the horizon (the only ones that
need history at all) a `max: 1` within-plan cap plus this window is exactly
"at most once per window_days".

**`at_least_once_per_window` turns the ceiling into a cadence.** "Khichdi once
in three weeks" is two requirements wearing one sentence: not twice inside the
window, AND not never. The ban half is satisfied by serving none at all, so on
its own it reads as enforced and lets a dish quietly disappear for months —
the same shape as the sprouts-gravy defect v2.07.01 found at Corning Chakan, a
cap written where a floor was asked for. Opt-in, so the other thirteen windows
in the fleet are unchanged.

The floor cannot be a pre-computed ban, because a ban removes candidates and a
floor demands one, so this half IS a CP-SAT constraint: when history says the
family is overdue, at least one cell in the horizon must take a matching dish.
It reads `recency_by_item` from the solver context — the same map the freshness
objective uses, read the other way round, since a dish ABSENT from it was never
served and is therefore maximally overdue rather than maximally fresh.

**The gap it guarantees is `window_days + horizon - 1`, not `window_days`.** A
plan may place the dish on any of its days, so a family that falls due on the
first day of a week can legitimately be served on the last. Pinning the exact
date would guarantee the tighter bound and is deliberately not done: it would
fix the dish to one weekday for ever and fight every other rule on the slot for
no benefit a kitchen can see. The config comment on each floor says the real
number.

`diagnose()` reports a selector that matches nothing so an inert rule is visible
rather than silently doing nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
from .relaxations import RELAXATION
from .selector_frequency_rule import SelectorFrequencyRule

# Inside the `src.menu_rules` tree `RelaxationCapture` listens on — a record
# logged outside it reaches nobody and /plan answers 200 with an empty
# `relaxations` list, which is the silent half of note 31.
logger = logging.getLogger(__name__)


class SelectorHistoryWindowRule(BaseMenuRule):
    """Config:
    {
        "type": "selector_history_window",
        "name": "fish_once_per_15_days",
        "selector": {"flag": "is_fish_dish"},   # selector_frequency grammar
        "exclude": {...},                        # optional
        "base_slot": "nonveg_main",              # scopes the ban; required
                                                 # for the floor
        "window_days": 15,
        "at_least_once_per_window": false        # optional; adds the floor
    }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SELECTOR_HISTORY_WINDOW
        self._inc = SelectorFrequencyRule._parse_matcher(rule_config.get('selector'))
        self._exc = SelectorFrequencyRule._parse_matcher(rule_config.get('exclude'))
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        wd = rule_config.get('window_days')
        self.window_days: Optional[int] = int(wd) if wd is not None else None
        self.at_least_once_per_window: bool = bool(
            rule_config.get('at_least_once_per_window', False))

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if self._inc is None:
            errs.append("a valid 'selector' is required")
        if not self.window_days or self.window_days < 1:
            errs.append("'window_days' must be a positive integer")
        if self.at_least_once_per_window and not self.base_slot:
            # The ban can go slot-wide; the floor must not. Unscoped, a leafy
            # DAL would satisfy "a leafy veg_dry every fortnight" and the slot
            # the cadence is about would still never see one — satisfied on
            # paper, missing on the plate, which is the exact failure the
            # floor exists to prevent.
            errs.append("'at_least_once_per_window' requires a 'base_slot'")
        return errs

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def _row_matches(self, row) -> bool:
        return (SelectorFrequencyRule._matches(row, self._inc)
                and not SelectorFrequencyRule._matches(row, self._exc))

    def matching_items(self, df: pd.DataFrame) -> Set[str]:
        """Lowercased item names in *df* that match the selector.

        Scoped to ``base_slot`` when one is set: the cadence "leafy veg_dry once
        per 15 days" is about the veg_dry slot, so a leafy *dal* served last week
        must NOT trigger it. Without this, matching by flag alone bans a whole
        family across every slot it appears in — the R31 window then starved
        Pune's dal on the week after a leafy dal was saved. `course_type` is the
        column the per-slot pools are built from, so it is the right scope.

        Lowercased because the ban is merged into ``banned_by_date`` and the
        solver compares candidate names case-folded there.
        """
        if self._inc is None or df is None or 'item' not in getattr(df, 'columns', []):
            return set()
        mask = df.apply(self._row_matches, axis=1)
        if self.base_slot and 'course_type' in df.columns:
            from ..preprocessor.column_mapper import _norm_str
            mask = mask & (df['course_type'].map(_norm_str) == _norm_str(self.base_slot))
        return {str(v).strip().lower() for v in df.loc[mask, 'item'].tolist()}

    #: The family resolved against this city's ontology, set by
    #: ``prepare_solver_inputs`` at the same moment it resolves the ban. The
    #: floor cannot resolve it itself — ``apply()`` is handed no ontology frame
    #: — and must NOT read it off the candidate rows, which are what is left
    #: AFTER the ceiling's ban: in the week following a khichdi there are none,
    #: so the clock would read "never served" at exactly the moment the dish
    #: was served most recently.
    resolved_items: Set[str] = frozenset()

    def _days_since_last(self, recency: Dict[str, int],
                         family: Set[str]) -> Optional[int]:
        """Days since ANY dish of the family was last served, or None if none
        of them was served inside the queried history window.

        ``min`` because the family's clock is set by its most recent member:
        a khichdi five days ago makes the family five days old even if a
        different khichdi last ran a year back.
        """
        seen = [recency[i] for i in family if i in recency]
        return min(seen) if seen else None

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        # The CEILING is enforced by a pre-computed history ban (see module
        # docstring), not by a constraint. Only the optional floor is CP-SAT.
        if not self.at_least_once_per_window or self._inc is None:
            return
        cells = context.get('cells') or []
        dates = context.get('dates') or []
        if not cells or not dates or not self.window_days:
            return

        lits = []
        for cell in cells:
            if self.base_slot and cell.base_slot != self.base_slot:
                continue
            for var, row in zip(cell.x_vars, cell.cand_rows):
                if self._row_matches(row):
                    lits.append(var)

        # Is the family overdue? Asked of the ONTOLOGY rather than of the
        # candidates, and asked BEFORE the availability check below, because
        # the two questions have to stay apart. The candidates are what is left
        # after the ceiling's own ban, so in the week after a khichdi there are
        # none — reading the clock off them would say "never served" at exactly
        # the moment the dish was served most recently, which is backwards.
        days_since = self._days_since_last(
            context.get('recency_by_item') or {}, set(self.resolved_items))
        # `None` means the family is absent from the history window entirely,
        # so it is overdue by definition. This is the one place `recency_by_item`
        # must NOT be read the way the freshness objective reads it, where a
        # missing dish is simply "fresh".
        if days_since is not None and days_since < self.window_days:
            return      # served recently enough; the ceiling governs from here

        # Due, and nothing to serve it with: the counter does not run the slot,
        # or every member of the family is cooled down. Degrade rather than
        # fail, and stamp it, because a cadence that quietly stopped holding is
        # indistinguishable from one that held (note 31). Only reachable when
        # the floor was actually DUE — a stand-down logged when nothing was
        # asked of the rule would make the channel mean two things.
        if not lits:
            logger.info(
                "%s: a %s from this cadence is due but none is available "
                "anywhere in the horizon, so the floor is not applied",
                self.name, self.base_slot or 'dish',
                extra={RELAXATION: self.name},
            )
            return

        model.AddBoolOr(lits)

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        diags: List[Diagnostic] = []
        if self._inc is None or ctx.df is None:
            return diags
        # A base_slot the counter does not serve makes the window inert.
        if (self.base_slot and ctx.active_base_slots is not None
                and self.base_slot not in ctx.active_base_slots):
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.PRE_FILTER,
                message=(
                    f"'{self.name}' targets base slot '{self.base_slot}', which "
                    f"this counter does not serve — the window is inert here."
                ),
                suggestion=(
                    f"Add a '{self.base_slot}' category to serve the dishes this "
                    f"cadence governs, or drop the rule for this counter."
                ),
                affected={'base_slot': self.base_slot,
                          'window_days': self.window_days},
            ))
            return diags
        # A selector that matches nothing enforces nothing. INFO, not WARNING:
        # a cadence for a dish family a city does not carry (oil-based bread in
        # Pune) is inert by design, the same "no action needed" class as the
        # theme-filter narrowing notes — not something an admin must fix.
        if not self.matching_items(ctx.df):
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.PRE_FILTER,
                message=(
                    f"'{self.name}' matches no dish in this city's item list, so "
                    f"the {self.window_days}-day cadence is inert here."
                ),
                suggestion=(
                    "No action needed unless the dish family should exist here — "
                    "then check the selector against the ontology columns."
                ),
                affected={'selector': self.config.get('selector'),
                          'window_days': self.window_days},
            ))
        return diags
