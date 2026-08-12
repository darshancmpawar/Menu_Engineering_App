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
"once per window_days".

`apply()` is a deliberate no-op — the enforcement is the pre-computed ban, not
a CP-SAT constraint. `matching_items()` and `window_days` are what `api.app`
reads to build that ban; `diagnose()` reports a selector that matches nothing so
an inert rule is visible rather than silently doing nothing.
"""

from __future__ import annotations

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
from .selector_frequency_rule import SelectorFrequencyRule


class SelectorHistoryWindowRule(BaseMenuRule):
    """Config:
    {
        "type": "selector_history_window",
        "name": "fish_once_per_15_days",
        "selector": {"flag": "is_fish_dish"},   # selector_frequency grammar
        "exclude": {...},                        # optional
        "base_slot": "nonveg_main",              # optional (diagnose only)
        "window_days": 15
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

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if self._inc is None:
            errs.append("a valid 'selector' is required")
        if not self.window_days or self.window_days < 1:
            errs.append("'window_days' must be a positive integer")
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

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        # The window is enforced by a pre-computed history ban (see module
        # docstring), not a CP-SAT constraint.
        pass

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
