"""Generic selector-driven frequency rule (Phase 1 rule-type framework).

One configurable rule type that covers most of the rulebook's count/frequency
constraints over the planning horizon, so rules live in config instead of one
hardcoded class each. A *selector* picks the matching items; the rule then
constrains how often they appear.

Config::

    {
        "type": "selector_frequency",
        "name": "mixed_veg_gravy_weekly",
        "selector": {"flag": "is_mixedveg_gravy"},   # exactly one selector key
        "base_slot": "veg_gravy",                     # optional slot scope
        "max": 1,            # horizon day-level: at most N days have a match
        "min": 0,            # horizon day-level: at least N days
        "exact": null,       # horizon day-level: exactly N days
        "non_consecutive": false,   # matched days may not be adjacent
        "daily_max": null    # per-day: at most N matching items in one day
    }

At least one of ``max``/``min``/``exact``/``daily_max``/``non_consecutive``
must be set. ``non_consecutive`` may stand alone (e.g. "sugar-syrup sweets
cannot appear on consecutive days" — no count, just an adjacency ban).

Selector keys: ``flag`` (column name), ``sub_category``, ``item``,
``key_ingredient``, ``primary_protein``, ``course_type``, ``cuisine_family``.

Counting is day-level for max/min/exact (how many days carry >= 1 match), which
equals occurrence count for single-per-day slots. ``daily_max`` is an
occurrence cap within a single day. ``min``/``exact`` targets are capped to what
the horizon can actually place (availability + non-consecutive aware) so the
rule relaxes gracefully instead of forcing an INFEASIBLE model; the pre-flight
diagnostics surface the shortfall.
"""

import logging
from typing import Dict, Any, List, Optional

from ortools.sat.python import cp_model

from .base_menu_rule import BaseMenuRule, MenuRuleType
from ..preprocessor.column_mapper import _norm_str

logger = logging.getLogger(__name__)

_SELECTOR_KEYS = frozenset({
    'flag', 'sub_category', 'item', 'key_ingredient', 'primary_protein',
    'course_type', 'cuisine_family',
})
_TEXT_COLS = {
    'sub_category': 'sub_category', 'item': 'item',
    'key_ingredient': 'key_ingredient', 'primary_protein': 'primary_protein',
    'course_type': 'course_type', 'cuisine_family': 'cuisine_family',
}


class SelectorFrequencyRule(BaseMenuRule):
    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.SELECTOR_FREQUENCY
        # Matcher = ('flag', col) | ('any_flag', [cols]) | (text_kind, value).
        # An optional `exclude` selector subtracts its matches (e.g. count
        # whole-legume dishes but exclude legume salads).
        self._inc = self._parse_matcher(rule_config.get('selector'))
        self._exc = self._parse_matcher(rule_config.get('exclude'))
        self.sel_kind = self._inc[0] if self._inc else ''
        self.sel_value = self._inc[1] if self._inc else ''
        self.base_slot: Optional[str] = rule_config.get('base_slot')
        self.max: Optional[int] = self._int_or_none(rule_config, 'max')
        self.min: Optional[int] = self._int_or_none(rule_config, 'min')
        self.exact: Optional[int] = self._int_or_none(rule_config, 'exact')
        self.daily_max: Optional[int] = self._int_or_none(rule_config, 'daily_max')
        self.non_consecutive: bool = bool(rule_config.get('non_consecutive', False))

    @staticmethod
    def _int_or_none(cfg, key):
        return int(cfg[key]) if key in cfg and cfg[key] is not None else None

    @staticmethod
    def _parse_matcher(sel):
        """Parse a selector dict into a matcher tuple, or None."""
        if not sel:
            return None
        if 'any_flag' in sel:
            flags = sel['any_flag']
            flags = list(flags) if isinstance(flags, (list, tuple)) else [flags]
            return ('any_flag', [str(f) for f in flags])
        present = [k for k in _SELECTOR_KEYS if k in sel]
        if len(present) == 1:
            k = present[0]
            raw = sel[k]
            return (k, raw if k == 'flag' else _norm_str(str(raw)))
        return None

    @staticmethod
    def _matches(row, matcher) -> bool:
        if matcher is None:
            return False
        kind, val = matcher
        if kind == 'flag':
            return int(row.get(val, 0) or 0) == 1
        if kind == 'any_flag':
            return any(int(row.get(f, 0) or 0) == 1 for f in val)
        col = _TEXT_COLS.get(kind, '')
        return _norm_str(str(row.get(col, ''))) == val

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.sel_kind:
            errs.append("selector must contain exactly one of " + ", ".join(sorted(_SELECTOR_KEYS)))
        if all(v is None for v in (self.max, self.min, self.exact, self.daily_max)) \
                and not self.non_consecutive:
            errs.append("at least one of max / min / exact / daily_max / non_consecutive is required")
        if self.exact is not None and (self.max is not None or self.min is not None):
            errs.append("exact cannot be combined with max/min")
        for k in ('max', 'min', 'exact', 'daily_max'):
            v = getattr(self, k)
            if v is not None and v < 0:
                errs.append(f"{k} must be >= 0 (got {v})")
        if self.max is not None and self.min is not None and self.min > self.max:
            errs.append(f"min ({self.min}) must be <= max ({self.max})")
        return errs

    def _row_matches(self, row) -> bool:
        return self._matches(row, self._inc) and not self._matches(row, self._exc)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        link_any = context.get('link_any_fn')
        if not cells or not link_any or not self.sel_kind:
            return

        day_has: List = []  # (day_index, bool_var) for days that CAN match
        for di in range(len(dates)):
            day_cells = [
                c for c in cells
                if c.d_idx == di and (self.base_slot is None or c.base_slot == self.base_slot)
            ]
            if not day_cells:
                continue
            lits = [
                v for c in day_cells
                for v, r in zip(c.x_vars, c.cand_rows)
                if self._row_matches(r)
            ]
            if not lits:
                continue
            # Per-day occurrence cap.
            if self.daily_max is not None:
                model.Add(sum(lits) <= self.daily_max)
            hv = model.NewBoolVar(f'{self.name}_day_{di}')
            link_any(model, lits, hv)
            day_has.append((di, hv))

        if not day_has:
            return
        hvars = [h for _, h in day_has]

        if self.max is not None:
            model.Add(sum(hvars) <= self.max)

        # min / exact: cap to what the horizon can actually place so a thin pool
        # relaxes instead of going INFEASIBLE.
        if self.non_consecutive:
            max_place, last = 0, -10
            for di, _ in day_has:
                if di - last >= 2:
                    max_place += 1
                    last = di
        else:
            max_place = len(day_has)

        # ...and cap to the number of DISTINCT matching dishes as well.
        #
        # ``max_place`` counts days on which a match could be placed, which is
        # not the same as how many days can *each carry a different* match. With
        # unique_items in force, N days of a selector needs N distinct matching
        # items. L&T's south-only counter has exactly one liquid dessert, yet
        # `liquid_desserts_twice_nonconsecutive` asked for two days: placeable on
        # all five, satisfiable on none, so the counter went INFEASIBLE with no
        # indication that a *dessert* rule was at fault. Bounding by distinct
        # matches makes the rule ask for what the pool can actually supply.
        distinct_matches = {
            _norm_str(r.get('item', ''))
            for c in cells
            if self.base_slot is None or c.base_slot == self.base_slot
            for r in c.cand_rows
            if self._row_matches(r)
        }
        distinct_matches.discard('')
        if distinct_matches:
            max_place = min(max_place, len(distinct_matches))

        if self.exact is not None:
            tgt = min(self.exact, max_place)
            if tgt != self.exact:
                logger.warning(
                    "%s: exact %d capped to %d — the eligible pool offers only "
                    "%d distinct matching dish(es) across %d placeable day(s). "
                    "Widen this client's item pools or lower the target.",
                    self.name, self.exact, tgt, len(distinct_matches),
                    len(day_has),
                )
            if tgt > 0:
                model.Add(sum(hvars) == tgt)
        if self.min is not None and self.min > 0:
            tgt = min(self.min, max_place)
            if tgt != self.min:
                logger.warning(
                    "%s: min %d capped to %d — the eligible pool offers only "
                    "%d distinct matching dish(es) across %d placeable day(s). "
                    "The rule is under-enforced; widen this client's item pools "
                    "or lower the target.",
                    self.name, self.min, tgt, len(distinct_matches),
                    len(day_has),
                )
            if tgt > 0:
                model.Add(sum(hvars) >= tgt)

        if self.non_consecutive:
            for (da, ha), (db, hb) in zip(day_has, day_has[1:]):
                if db == da + 1:
                    model.Add(ha + hb <= 1)
