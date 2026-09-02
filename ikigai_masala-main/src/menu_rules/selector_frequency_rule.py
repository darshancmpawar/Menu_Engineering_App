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
        "max_per_week": null,# CALENDAR-week day-level: at most N days a week
        "min": 0,            # horizon day-level: at least N days
        "exact": null,       # horizon day-level: exactly N days
        "non_consecutive": false,   # matched days may not be adjacent
        "daily_max": null,   # per-day: at most N matching items in one day
        "daily_min": null,   # per-day: at least N matching items EVERY day
        "allowed_day_types": null,     # themes the selector may appear on
        "forbidden_weekdays": null     # weekdays it may NOT appear on
    }

At least one of ``max``/``min``/``exact``/``daily_max``/``daily_min``/
``non_consecutive`` must be set. ``non_consecutive`` may stand alone (e.g. "sugar-syrup sweets
cannot appear on consecutive days" — no count, just an adjacency ban).

Selector keys: ``flag`` (column name), ``sub_category``, ``item``,
``key_ingredient``, ``primary_protein``, ``course_type``, ``cuisine_family``.
Combinators: ``any_flag`` (any of these flag columns), ``any_of`` / ``all_of``
(a list of sub-selectors, OR / AND), ``name_contains`` (substrings of the dish
NAME).

``max`` counts across the WHOLE HORIZON, which is what "at most N" has always
meant here and is right for a one-week plan — but it silently tightens as the
plan grows: a rule named `*_weekly` with ``max: 1`` means "once a fortnight" on
14 days and "once in three weeks" on 21. That is not a hypothetical. Sixty rules
across the shipped configs are named that way, and on a 14-day horizon it is
what blocks most of the fleet: 74 of 85 counters diagnose clean at 7 days and
only 34 at 14, almost all of them on `nonveg_biryani_once_per_week`,
`mixedveg_pulao_biryani_weekly` or `kootu_twice_weekly`.

``max_per_week`` is the fix, and it means what the rule name says: at most N
days **in each calendar week**. Weeks are ISO (Monday-Sunday), the same
boundary `chinese_continental` already resolves its parity on, so a rule reads
the same way whatever horizon it is planned over. On a Monday-start week-long
plan it is identical to ``max``; beyond that it stops over-constraining. Note it
is a CALENDAR week, not a rolling 7 days, so a plan starting mid-week may place
two matches within seven consecutive days either side of the boundary — that is
the client's own "once a week" and the looser reading is deliberate.

The two may be combined: ``max_per_week`` for the recurring cadence and ``max``
for an absolute ceiling on the plan.

Counting is day-level for max/min/exact (how many days carry >= 1 match), which
equals occurrence count for single-per-day slots. ``daily_max`` is an
occurrence cap within a single day, and ``daily_min`` its floor — the way to say
"every day" without depending on the horizon length, since `min` counts days
across the horizon (`min: 5` is "5 of 5" on a week but "5 of 10" on a fortnight). ``min``/``exact`` targets are capped to what
the horizon can actually place (availability + non-consecutive aware) so the
rule relaxes gracefully instead of forcing an INFEASIBLE model; the pre-flight
diagnostics surface the shortfall.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from ortools.sat.python import cp_model

from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnoseContext,
    DiagnosticPhase,
    DiagnosticSeverity,
    MenuRuleType,
)
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
#: Both spellings, matching `slot_day_restriction_rule`'s own table — a config
#: writing "sat" for one rule and "saturday" for the other should not surprise
#: anyone.
_WEEKDAY_TOKENS = {
    'mon': 0, 'monday': 0, 'tue': 1, 'tuesday': 1, 'wed': 2, 'wednesday': 2,
    'thu': 3, 'thursday': 3, 'fri': 4, 'friday': 4, 'sat': 5, 'saturday': 5,
    'sun': 6, 'sunday': 6,
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
        # `base_slot` accepts a name OR a list of names. A list is needed for a
        # constraint that spans slots — "a protein source somewhere on the
        # plate" is satisfied by the rice, the gravy, the veg dry, the salad or
        # the dal, and scoping to any single one of them would be a different
        # (and wrong) rule. `self.base_slot` stays the single name for the
        # one-slot case so diagnose() and every existing config are unchanged.
        bs = rule_config.get('base_slot')
        if isinstance(bs, (list, tuple, set)):
            self.base_slots: Optional[Set[str]] = {str(x) for x in bs if str(x).strip()}
            self.base_slot: Optional[str] = None
        else:
            self.base_slots = {str(bs)} if bs else None
            self.base_slot = bs
        self.max: Optional[int] = self._int_or_none(rule_config, 'max')
        self.max_per_week: Optional[int] = self._int_or_none(
            rule_config, 'max_per_week')
        self.min: Optional[int] = self._int_or_none(rule_config, 'min')
        self.exact: Optional[int] = self._int_or_none(rule_config, 'exact')
        self.daily_max: Optional[int] = self._int_or_none(rule_config, 'daily_max')
        self.daily_min: Optional[int] = self._int_or_none(rule_config, 'daily_min')
        self.non_consecutive: bool = bool(rule_config.get('non_consecutive', False))
        # Restrict the selector to days of these themes. A nonveg biryani belongs
        # on a biryani day; without this, `mix` days (which the theme filter does
        # not narrow at all) were free to serve one, so a themed counter got
        # biryani on Monday and none on its actual biryani day.
        adt = rule_config.get('allowed_day_types')
        self.allowed_day_types: Optional[Set[str]] = (
            {str(t).strip().lower() for t in adt} if adt else None
        )
        # Forbid the selector on named WEEKDAYS. `allowed_day_types` is the
        # theme-shaped twin and cannot express this: TCL's "no baby corn, paneer
        # or mushroom on Saturday and Sunday" is about the weekend service, not
        # about a cuisine, and its weekend days carry no theme of their own.
        # `slot_day_restriction` is the wrong tool too — that stands a whole slot
        # down, and the client still wants a gravy on Saturday, just not a paneer
        # one. Same ban-and-degrade path as `allowed_day_types`.
        self.forbidden_weekdays: Optional[Set[int]] = None
        fwd = rule_config.get('forbidden_weekdays')
        if fwd:
            days = {
                _WEEKDAY_TOKENS[str(t).strip().lower()]
                for t in fwd
                if str(t).strip().lower() in _WEEKDAY_TOKENS
            }
            self.forbidden_weekdays = days or None

    @staticmethod
    def _int_or_none(cfg, key):
        return int(cfg[key]) if key in cfg and cfg[key] is not None else None

    @staticmethod
    def _parse_matcher(sel):
        """Parse a selector dict into a matcher tuple, or None.

        ``any_of`` takes a LIST of selectors and matches a row satisfying any of
        them. ``any_flag`` already covers "any of these flags", but a rule naming
        several *ingredients* — "not soya, baby corn, chole or mushroom" — mixes
        flags and text columns and needs the general form.

        ``name_contains`` takes a substring (or list of them) and matches on the
        dish NAME. It is the escape hatch for a family the ontology's columns file
        unreliably: `key_ingredient == 'baby_corn'` tags 67 Bangalore rows of
        which 3 are baby-corn dishes (it is the de-facto default for a mixed
        salad) while the 34 dishes actually named after baby corn are tagged
        `corn` / `bell_pepper` / `cauliflower`. Prefer a column when one is
        trustworthy — a substring match is blunt and cannot see intent.
        """
        if not sel:
            return None
        if 'name_contains' in sel:
            raw = sel['name_contains']
            raw = list(raw) if isinstance(raw, (list, tuple)) else [raw]
            needles = [_norm_str(str(s)) for s in raw if str(s).strip()]
            return ('name_contains', needles) if needles else None
        if 'any_of' in sel:
            raw = sel['any_of']
            raw = list(raw) if isinstance(raw, (list, tuple)) else [raw]
            parts = [SelectorFrequencyRule._parse_matcher(s) for s in raw]
            parts = [p for p in parts if p is not None]
            return ('any_of', parts) if parts else None
        # `all_of` is the conjunction `any_flag` and `any_of` cannot express.
        # "An egg GRAVY" is two flags — `is_egg_dish` AND `is_nonveg_gravy` —
        # and neither column alone says it: ICON Chn's Monday egg gravy came
        # back as a boiled egg under `is_egg_dish`, and `is_nonveg_gravy` alone
        # is every chicken curry on the list. Sub-selectors nest, so a
        # conjunction of disjunctions works.
        if 'all_of' in sel:
            raw = sel['all_of']
            raw = list(raw) if isinstance(raw, (list, tuple)) else [raw]
            parts = [SelectorFrequencyRule._parse_matcher(s) for s in raw]
            parts = [p for p in parts if p is not None]
            return ('all_of', parts) if parts else None
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
        if kind == 'any_of':
            return any(SelectorFrequencyRule._matches(row, m) for m in val)
        if kind == 'all_of':
            return all(SelectorFrequencyRule._matches(row, m) for m in val)
        if kind == 'name_contains':
            name = _norm_str(str(row.get('item', '')))
            return bool(name) and any(nd in name for nd in val)
        col = _TEXT_COLS.get(kind, '')
        return _norm_str(str(row.get(col, ''))) == val

    def validate_config(self) -> bool:
        return not self.validation_errors()

    def validation_errors(self) -> List[str]:
        errs: List[str] = []
        if not self.sel_kind:
            errs.append("selector must contain exactly one of " + ", ".join(sorted(_SELECTOR_KEYS)))
        if all(v is None for v in (self.max, self.min, self.exact, self.daily_max,
                                   self.daily_min, self.max_per_week)) \
                and not self.non_consecutive \
                and not self.forbidden_weekdays:
            errs.append("at least one of max / max_per_week / min / exact / "
                        "daily_max / non_consecutive / forbidden_weekdays is "
                        "required")
        if self.exact is not None and self.max_per_week is not None:
            errs.append("exact cannot be combined with max_per_week")
        if (self.max is not None and self.max_per_week is not None
                and self.max_per_week > self.max):
            errs.append(f"max_per_week ({self.max_per_week}) must be <= max "
                        f"({self.max})")
        if self.exact is not None and (self.max is not None or self.min is not None):
            errs.append("exact cannot be combined with max/min")
        for k in ('max', 'min', 'exact', 'daily_max', 'daily_min',
                  'max_per_week'):
            v = getattr(self, k)
            if v is not None and v < 0:
                errs.append(f"{k} must be >= 0 (got {v})")
        if self.max is not None and self.min is not None and self.min > self.max:
            errs.append(f"min ({self.min}) must be <= max ({self.max})")
        return errs

    def _row_matches(self, row) -> bool:
        return self._matches(row, self._inc) and not self._matches(row, self._exc)

    def _ban_leaves_every_cell_fillable(self, day_cells) -> bool:
        """True when every cell still has a non-matching candidate to fall back
        on, so forbidding the selector cannot empty a cell."""
        for cell in day_cells:
            if not any(not self._row_matches(r) for r in cell.cand_rows):
                return False
        return True

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        day_types = context.get('day_types', [])
        link_any = context.get('link_any_fn')
        if not cells or not link_any or not self.sel_kind:
            return

        day_has: List = []  # (day_index, bool_var) for days that CAN match
        for di in range(len(dates)):
            day_cells = [
                c for c in cells
                if c.d_idx == di and (self.base_slots is None
                                      or c.base_slot in self.base_slots)
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
            # Theme restriction: forbid the selector outright on a day whose
            # theme is not in `allowed_day_types`. Skipped when banning would
            # leave the day's cells nothing to choose from — a slot whose whole
            # pool matches the selector must still be fillable, so an
            # unsatisfiable ban degrades instead of failing the plan (diagnose()
            # reports it).
            if self.allowed_day_types is not None:
                day_type = str(day_types[di]).lower() if di < len(day_types) else ''
                if day_type not in self.allowed_day_types:
                    if self._ban_leaves_every_cell_fillable(day_cells):
                        for lit in lits:
                            model.Add(lit == 0)
                        continue
                    logger.info(
                        "%s: day %d (%s) is outside allowed_day_types but the "
                        "slot has nothing else to offer; ban skipped",
                        self.name, di, day_type,
                    )
            # Weekday ban, same degrade-rather-than-fail rule as the theme ban
            # above: a slot whose whole pool matches the selector must still be
            # fillable on a forbidden weekday.
            if self.forbidden_weekdays and di < len(dates):
                wd = getattr(dates[di], 'weekday', None)
                if callable(wd) and wd() in self.forbidden_weekdays:
                    if self._ban_leaves_every_cell_fillable(day_cells):
                        for lit in lits:
                            model.Add(lit == 0)
                        continue
                    logger.info(
                        "%s: day %d falls on a forbidden weekday but the slot "
                        "has nothing else to offer; ban skipped",
                        self.name, di,
                    )
            # Per-day occurrence cap.
            if self.daily_max is not None:
                model.Add(sum(lits) <= self.daily_max)
            # Per-day floor — the twin of daily_max, and the only way to say
            # "every day" independently of the horizon length. `min` counts days
            # across the horizon, so `min: 5` means "5 of 5" on a week but "5 of
            # 10" on a fortnight; `daily_min` means the same thing whatever the
            # horizon. Capped to what the day can actually place, so a day whose
            # cells offer fewer matches than the floor relaxes to what exists
            # instead of taking the plan down (`diagnose()` reports the gap).
            if self.daily_min is not None:
                want = min(self.daily_min, len(lits), len(day_cells))
                if want > 0:
                    model.Add(sum(lits) >= want)
                if want < self.daily_min:
                    logger.info(
                        "%s: day %d can place only %d of the %d required "
                        "matching item(s); floor relaxed for that day",
                        self.name, di, want, self.daily_min,
                    )
            hv = model.NewBoolVar(f'{self.name}_day_{di}')
            link_any(model, lits, hv)
            day_has.append((di, hv))

        if not day_has:
            return
        hvars = [h for _, h in day_has]

        if self.max is not None:
            model.Add(sum(hvars) <= self.max)

        # ...and the per-CALENDAR-week cap, which is what a rule named `*_weekly`
        # actually means. One constraint per ISO week present in the horizon, so
        # the rule reads the same whether it is planned over 5 days or 25.
        if self.max_per_week is not None and dates:
            by_week: Dict[Any, List[Any]] = {}
            for di, hv in day_has:
                if di >= len(dates):                       # pragma: no cover
                    continue
                iso = dates[di].isocalendar()
                by_week.setdefault((iso[0], iso[1]), []).append(hv)
            for week, wv in by_week.items():
                model.Add(sum(wv) <= self.max_per_week)

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
            if self.base_slots is None or c.base_slot in self.base_slots
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

    # Populated by the diagnostics aggregator so diagnose() can replay the
    # pre-filter chain and see the pool the solver will actually receive.
    _peer_rules: List[Any] = []

    def _eligible_days(self, ctx: "DiagnoseContext"):
        """Return ``(placeable_days, distinct_matching_items)`` for the horizon.

        Mirrors what ``apply()`` computes, but from the pre-flight pools, so the
        numbers reported here are the numbers the constraint will be built from.
        """
        slots = (
            sorted(self.base_slots) if self.base_slots
            else list(ctx.active_base_slots or [])
        )
        days = 0
        distinct: Set[str] = set()
        for d in ctx.dates:
            day_has_match = False
            for base in slots:
                if base not in ctx.pools:
                    continue
                if (d, base) in (ctx.skip_cells or set()):
                    continue
                pool = ctx.pools[base]
                if base in ('rice', 'healthy_rice') and len(pool) > 0:
                    pool = pool[~pool['item'].isin(ctx.cfg.rice_exclude_items)]
                day_type = ctx.day_types.get(d, '')
                filter_ctx = {
                    'cfg': ctx.cfg, 'banned_by_date': {},
                    'ricebread_ban_day': {}, 'pools': ctx.pools,
                    'slot_num': None,
                }
                for rule in (self._peer_rules or []):
                    pool = rule.pre_filter_pool(
                        pool, d, base, day_type, filter_ctx)
                if not len(pool):
                    continue
                for _i, row in pool.iterrows():
                    if self._row_matches(row):
                        day_has_match = True
                        name = _norm_str(row.get('item', ''))
                        if name:
                            distinct.add(name)
            if day_has_match:
                days += 1
        return days, len(distinct)

    def _forced_days(self, ctx: "DiagnoseContext") -> int:
        """Days on which a match is *unavoidable* for this rule's slot.

        A day is forced when every item still eligible for the slot matches the
        selector, so whatever the solver picks there counts against ``max``.
        This is what makes a ``max`` rule collide with a theme map: Amadeus's
        Chinese counter is themed ``chinese_continental`` every weekday, which on
        an odd ISO week resolves to *continental* on all five days, and the theme
        filter then narrows ``rice`` to continental rice only — five forced days
        against ``continental_rice_weekly``'s ``max: 1``.

        Counted per *day*, matching how ``apply()`` counts ``max``.
        """
        if not self.base_slot or self.base_slot not in ctx.pools:
            # No slot scope, so the pool-exhaustion half cannot be asked — but a
            # composition can still force the selector, and a slot-less cap is
            # the easiest kind to contradict because it counts a match anywhere
            # on the plate. Chennai's slot-less `kootu_twice_weekly` against
            # TCL's "the dal is a kootu, daily" was invisible until this.
            from .slot_composition_rule import days_forced_by_composition
            return days_forced_by_composition(
                self._peer_rules, ctx, None, self._row_matches,
            )
        active = ctx.active_base_slots
        if active is not None and self.base_slot not in active:
            return 0

        forced = 0
        self._forced_dates = []
        for d in ctx.dates:
            if (d, self.base_slot) in (ctx.skip_cells or set()):
                continue
            pool = ctx.pools[self.base_slot]
            if self.base_slot in ('rice', 'healthy_rice') and len(pool) > 0:
                pool = pool[~pool['item'].isin(ctx.cfg.rice_exclude_items)]
            day_type = ctx.day_types.get(d, '')
            filter_ctx = {
                'cfg': ctx.cfg, 'banned_by_date': {}, 'ricebread_ban_day': {},
                'pools': ctx.pools, 'slot_num': None,
            }
            for rule in (self._peer_rules or []):
                pool = rule.pre_filter_pool(
                    pool, d, self.base_slot, day_type, filter_ctx)
            if not len(pool):
                continue
            if all(self._row_matches(row) for _i, row in pool.iterrows()):
                forced += 1
                self._forced_dates.append(d)

        # A composition rule mandating a matching item forces the selector just
        # as hard as a pool that offers nothing else.
        from .slot_composition_rule import dates_forced_by_composition
        by_composition = dates_forced_by_composition(
            self._peer_rules, ctx, self.base_slot, self._row_matches,
        )
        # Dates, not counts — see the same change in `nonveg_rules.py`. A
        # `max_per_week` cap needs to know WHICH days are forced so it can ask
        # whether any single week exceeds it.
        self._forced_dates = sorted(set(self._forced_dates) | set(by_composition))
        return max(forced, len(by_composition), len(self._forced_dates))

    def diagnose(self, ctx: "DiagnoseContext") -> List["Diagnostic"]:
        """Report when this rule cannot ask for what it is configured to ask.

        ``apply()`` caps ``min``/``exact`` to what the pool can supply so a thin
        pool relaxes instead of going INFEASIBLE. That relaxation is correct, but
        it used to be invisible: a rule targeting a flag no item carries — or
        fewer items than days — silently stopped constraining anything, and the
        menu looked fine while a client requirement went unenforced. This is the
        surface that says so.

        Severities are deliberately non-blocking. ``apply()`` caps the target to
        what is achievable and the solve proceeds, so a shortfall never makes the
        plan impossible — reporting it as an ERROR would gate /plan with a 422 for
        a counter that generates a perfectly good menu (L&T's south counter has
        one liquid dessert against a target of two, and is otherwise fine).

          * WARNING — target capped: the rule is partially enforced, and the
                      response says by how much.
          * INFO    — the selector matches nothing anywhere, so the rule is inert.
        """
        diags: List["Diagnostic"] = []

        # A `max` is NOT automatically satisfiable. When the theme filter leaves
        # the slot with nothing *but* matching items on more days than `max`
        # allows, the two rules contradict each other and the solve comes back
        # INFEASIBLE with no explanation — which is exactly how Amadeus's Chinese
        # counter failed while this pass reported "would_succeed: true". Provable
        # from the pools, so it is an ERROR and /plan answers 422 with the fix.
        cap = self.max if self.max is not None else self.exact
        if cap is not None or self.max_per_week is not None:
            forced = self._forced_days(ctx)
            # A per-week cap is only contradicted when a SINGLE week is forced
            # past it. Comparing the horizon total against a weekly number is
            # what made every `*_weekly` rule look impossible on a fortnight.
            if self.max_per_week is not None:
                by_week: Dict[Any, int] = {}
                for d in getattr(self, '_forced_dates', []):
                    iso = d.isocalendar()
                    key = (iso[0], iso[1])
                    by_week[key] = by_week.get(key, 0) + 1
                worst = max(by_week.values(), default=0)
                if cap is None or self.max_per_week < cap:
                    cap, forced = self.max_per_week, worst
                elif worst > self.max_per_week:
                    cap, forced = self.max_per_week, worst
            if cap is not None and forced > cap:
                sel_desc = f"{self.sel_kind}={self.sel_value!r}"
                where = (f"for '{self.base_slot}'" if self.base_slot
                         else "somewhere on this counter")
                diags.append(Diagnostic(
                    rule=self.name, rule_type=self.rule_type.value,
                    severity=DiagnosticSeverity.ERROR,
                    phase=DiagnosticPhase.APPLY,
                    message=(
                        f"This counter's rules leave {sel_desc} unavoidable "
                        f"{where} on {forced} day(s), but this rule allows "
                        f"{cap}. Those rules contradict each other, so no menu "
                        f"can satisfy both."
                    ),
                    suggestion=(
                        f"Raise this rule's limit to {forced}, add "
                        f"\"{self.name}\" to this client's `disable` list in "
                        f"client_rules.json if the limit is not meant to apply "
                        f"to this counter, or give the counter day themes that "
                        f"do not force {sel_desc} every day."
                    ),
                    affected={
                        'selector': sel_desc,
                        'base_slot': self.base_slot,
                        'limit': cap,
                        'forced_days': forced,
                    },
                ))
                return diags

        if self.min is None and self.exact is None:
            # min/exact shortfalls are the only remaining failure mode; a `max`
            # that is not force-violated above only ever tightens.
            return diags

        placeable, distinct = self._eligible_days(ctx)
        target = self.exact if self.exact is not None else self.min
        if not target or target <= 0:
            return diags
        achievable = min(placeable, distinct) if distinct else 0
        if achievable >= target:
            return diags

        sel = f"{self.sel_kind}={self.sel_value!r}"
        scope = f" in {self.base_slot}" if self.base_slot else ""
        shared = {
            'selector': sel,
            'base_slot': self.base_slot,
            'target': target,
            'placeable_days': placeable,
            'distinct_items': distinct,
            'achievable': achievable,
        }

        if distinct == 0:
            diags.append(Diagnostic(
                rule=self.name, rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.INFO,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"No eligible item matches {sel}{scope}, so this rule is "
                    f"inert — its target of {target} is not enforced at all."
                ),
                suggestion=(
                    "Check the selector spelling against the ontology columns, "
                    "populate the flag in menu_items.xlsx, or remove the rule. "
                    "A selector that matches nothing silently drops a client "
                    "requirement."
                ),
                affected=shared,
            ))
            return diags

        wording = (
            f"Requires exactly {target} day(s)" if self.exact is not None
            else f"Asks for at least {target} day(s)"
        )
        diags.append(Diagnostic(
            rule=self.name, rule_type=self.rule_type.value,
            severity=DiagnosticSeverity.WARNING,
            phase=DiagnosticPhase.APPLY,
            message=(
                f"{wording} with {sel}{scope}, but only {achievable} can be "
                f"achieved ({distinct} distinct matching item(s) across "
                f"{placeable} placeable day(s)). The rule is enforced at "
                f"{achievable} — partially, not as configured."
            ),
            suggestion=(
                f"Widen this client's source_pools, add matching items to the "
                f"ontology, or lower the target to {achievable} so the config "
                f"states what is actually achievable."
            ),
            affected=shared,
        ))
        return diags
