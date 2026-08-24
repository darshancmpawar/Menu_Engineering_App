"""
Slot-day restriction rule: skip a slot entirely on certain weekdays.

This rule does not participate in the pre-filter or CP-SAT phases.
Instead, it exposes ``compute_skip_cells()`` which the API layer calls
before constructing the solver.  The returned ``(date, base_slot)`` pairs
are forwarded to ``MenuSolver(skip_cells=…)`` which prevents cell
creation for those combinations.

By default all expansions of the base slot are skipped together (e.g. if a
client has ``nonveg_main`` count=2, both ``nonveg_main__1`` and
``nonveg_main__2`` are removed on restricted days). An optional
``slot_indices`` narrows that to the named expansions, which is how a counter
serves *fewer* of a slot on some days rather than none: TCL runs two flavoured
rices Monday to Friday and one on Saturday, so only ``rice__2`` stands down.
"""

import datetime as dt
from typing import Dict, Any, List, Optional, Set, Tuple

from ortools.sat.python import cp_model
from .base_menu_rule import BaseMenuRule, MenuRuleType


_WEEKDAY_TOKENS: Dict[str, int] = {
    'mon': 0, 'monday': 0,
    'tue': 1, 'tuesday': 1,
    'wed': 2, 'wednesday': 2,
    'thu': 3, 'thursday': 3,
    'fri': 4, 'friday': 4,
    'sat': 5, 'saturday': 5,
    'sun': 6, 'sunday': 6,
}


class SlotDayRestrictionRule(BaseMenuRule):
    """
    Config example::

        {
            "type": "slot_day_restriction",
            "name": "tekion_nonveg_mwf",
            "base_slot": "nonveg_main",
            "allowed_weekdays": ["mon", "wed", "fri"]
        }

    Add ``slot_indices`` to stand down only some expansions, leaving the rest
    of the family solved normally::

        {
            "type": "slot_day_restriction",
            "name": "tcl_one_rice_on_saturday",
            "base_slot": "rice",
            "slot_indices": [2],
            "allowed_weekdays": ["mon", "tue", "wed", "thu", "fri", "sun"]
        }
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SLOT_DAY_RESTRICTION
        self.base_slot: str = rule_config.get('base_slot', '')
        raw_days = rule_config.get('allowed_weekdays', [])
        self.allowed_weekdays: Set[int] = set()
        for tok in raw_days:
            if isinstance(tok, str):
                idx = _WEEKDAY_TOKENS.get(tok.strip().lower())
                if idx is not None:
                    self.allowed_weekdays.add(idx)
        self.slot_indices: Optional[List[int]] = None
        raw_idx = rule_config.get('slot_indices')
        if isinstance(raw_idx, (list, tuple)):
            kept = []
            for tok in raw_idx:
                try:
                    n = int(tok)
                except (TypeError, ValueError):
                    continue
                if n >= 1 and n not in kept:
                    kept.append(n)
            self.slot_indices = kept or None

    def validate_config(self) -> bool:
        return bool(self.base_slot) and len(self.allowed_weekdays) > 0

    def compute_skip_cells(
        self, dates: List[dt.date],
    ) -> Set[Tuple[dt.date, str]]:
        """Cells to skip: ``(date, base_slot)``, or one entry per named
        expansion when ``slot_indices`` is set.

        The two entry shapes are both understood by
        ``src.solver._helpers.cell_is_skipped``, so a per-expansion skip needs
        no solver change — it is the same mechanism a client constant uses to
        pin ``nonveg_main__2`` while ``__1`` is still solved.
        """
        targets = ([f'{self.base_slot}__{i}' for i in self.slot_indices]
                   if self.slot_indices else [self.base_slot])
        return {
            (d, slot)
            for d in dates
            if d.weekday() not in self.allowed_weekdays
            for slot in targets
        }

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        pass  # Cell skipping is handled by the solver, not CP-SAT constraints
