"""Five engine gaps the four new Chennai clients walked into.

Each one is a case where the config said something the engine could not express,
or expressed it and then contradicted itself. Four of the five failed *silently*
in the sense that mattered — the plan came back INFEASIBLE with no rule named,
or `/diagnose` answered "would_succeed: true" for a counter that could not
solve — which is the failure mode this repo cares about most.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.menu_rules.selector_frequency_rule import SelectorFrequencyRule
from src.menu_rules.slot_day_restriction_rule import SlotDayRestrictionRule
from src.solver.menu_solver import MenuSolver, SolverConfig

MON = dt.date(2026, 8, 10)
WEEK = [MON + dt.timedelta(days=i) for i in range(7)]


class TestSkippingOneExpansion:
    """TCL runs two flavoured rices Monday to Friday and one on Saturday.

    `slot_day_restriction` skipped every expansion of a base slot, so the only
    thing it could say was "no rice at all on Saturday".
    """

    def test_without_slot_indices_the_whole_family_stands_down(self):
        rule = SlotDayRestrictionRule({
            'name': 'r', 'base_slot': 'rice',
            'allowed_weekdays': ['mon', 'tue', 'wed', 'thu', 'fri'],
        })
        skips = rule.compute_skip_cells(WEEK)
        assert (WEEK[5], 'rice') in skips
        assert (WEEK[0], 'rice') not in skips

    def test_with_slot_indices_only_the_named_expansion_does(self):
        rule = SlotDayRestrictionRule({
            'name': 'r', 'base_slot': 'rice', 'slot_indices': [2],
            'allowed_weekdays': ['mon', 'tue', 'wed', 'thu', 'fri', 'sun'],
        })
        skips = rule.compute_skip_cells(WEEK)
        assert skips == {(WEEK[5], 'rice__2')}
        # The bare base slot must NOT be skipped, or `cell_is_skipped` would
        # drop `rice__1` with it — the two entry shapes are read together.
        assert (WEEK[5], 'rice') not in skips

    def test_the_solver_reads_both_entry_shapes(self):
        from src.solver._helpers import cell_is_skipped
        skips = {(WEEK[5], 'rice__2')}
        assert cell_is_skipped(skips, WEEK[5], 'rice__2')
        assert not cell_is_skipped(skips, WEEK[5], 'rice__1')
        assert cell_is_skipped({(WEEK[5], 'rice')}, WEEK[5], 'rice__1')

    @pytest.mark.parametrize('raw, want', [
        ([2], [2]),
        (['2'], [2]),
        ([2, 2], [2]),
        ([0, -1], None),          # an index below 1 names no expansion
        ([], None),
        (None, None),
        ('2', None),              # a bare string is not a list of indices
    ])
    def test_slot_indices_parsing(self, raw, want):
        rule = SlotDayRestrictionRule({
            'name': 'r', 'base_slot': 'rice', 'slot_indices': raw,
            'allowed_weekdays': ['mon'],
        })
        assert rule.slot_indices == want


class TestForbiddenWeekdays:
    """TCL: "no item like baby corn, panner and mushroom will given on sat and
    sun". `allowed_day_types` is theme-shaped and cannot say it — the weekend
    days carry no theme of their own — and `slot_day_restriction` stands a whole
    slot down, while the client still wants a gravy on Saturday.
    """

    def test_it_parses_both_spellings(self):
        rule = SelectorFrequencyRule({
            'name': 'r', 'selector': {'key_ingredient': 'paneer'},
            'forbidden_weekdays': ['sat', 'sunday'],
        })
        assert rule.forbidden_weekdays == {5, 6}

    def test_it_stands_alone_as_a_constraint(self):
        """Every other field is a count, so without this the rule would be
        rejected as "at least one of max / min / exact ... is required"."""
        rule = SelectorFrequencyRule({
            'name': 'r', 'selector': {'key_ingredient': 'paneer'},
            'forbidden_weekdays': ['sat'],
        })
        assert rule.validate_config()

    def test_an_unparseable_day_leaves_it_unset(self):
        rule = SelectorFrequencyRule({
            'name': 'r', 'selector': {'key_ingredient': 'paneer'},
            'forbidden_weekdays': ['someday'], 'max': 1,
        })
        assert rule.forbidden_weekdays is None


class TestAllOfSelector:
    """"An egg GRAVY" is two flags, and `any_flag` is an OR."""

    @staticmethod
    def _row(**kw):
        base = {'item': 'x', 'is_egg_dish': 0, 'is_nonveg_gravy': 0,
                'is_nonveg_dry': 0}
        base.update(kw)
        return pd.Series(base)

    def test_it_requires_every_part(self):
        m = SelectorFrequencyRule._parse_matcher({'all_of': [
            {'flag': 'is_egg_dish'}, {'flag': 'is_nonveg_gravy'}]})
        assert SelectorFrequencyRule._matches(
            self._row(is_egg_dish=1, is_nonveg_gravy=1), m)
        # A boiled egg is an egg dish and NOT a gravy — the dish that made the
        # difference, since it is what ICON's Monday came back with.
        assert not SelectorFrequencyRule._matches(
            self._row(is_egg_dish=1, is_nonveg_dry=1), m)
        # A chicken curry is a gravy and not an egg dish.
        assert not SelectorFrequencyRule._matches(
            self._row(is_nonveg_gravy=1), m)

    def test_it_nests_with_any_of(self):
        m = SelectorFrequencyRule._parse_matcher({'all_of': [
            {'flag': 'is_egg_dish'},
            {'any_of': [{'flag': 'is_nonveg_gravy'},
                        {'flag': 'is_nonveg_dry'}]}]})
        assert SelectorFrequencyRule._matches(
            self._row(is_egg_dish=1, is_nonveg_dry=1), m)
        assert not SelectorFrequencyRule._matches(
            self._row(is_nonveg_dry=1), m)

    def test_an_empty_list_yields_no_matcher(self):
        assert SelectorFrequencyRule._parse_matcher({'all_of': []}) is None


class TestAPinnedDishIsAStaple:
    """World Bank pins a chicken biryani, a boiled egg and a bone salna into its
    non-veg station every day. A pin naming a real dish narrows the cell rather
    than being stamped, so `unique_items` saw the same dish five times and each
    pin alone made the counter INFEASIBLE with no rule named.

    `api.app` already applies the reasoning to a single-expansion slot — a daily
    string there drops the slot "because the same dish cannot occupy five days
    unless it is a staple". Pinning it every day IS declaring it one.
    """

    @staticmethod
    def _solver(forced):
        cfg = SolverConfig()
        cfg.forced_items = forced
        s = MenuSolver.__new__(MenuSolver)
        s.cfg = cfg
        s.menu_rules = []
        return s

    def test_a_dish_pinned_on_two_days_is_declared_repeatable(self):
        s = self._solver({
            (WEEK[0], 'nonveg_main__2'): 'chicken_biryani',
            (WEEK[1], 'nonveg_main__2'): 'chicken_biryani',
        })
        declared = s._repeatable_declarations()
        assert declared == {'nonveg_main': [(('item', 'chicken_biryani'), None)]}

    def test_a_one_day_pin_repeats_nothing(self):
        """A weekday map or a festival pin must stay under unique_items."""
        s = self._solver({(WEEK[0], 'nonveg_main__2'): 'chicken_biryani'})
        assert s._repeatable_declarations() == {}

    def test_unique_items_actually_honours_the_declaration(self):
        """The shape has to be a PARSED matcher tuple, not a selector dict —
        `_matches` unpacks `(kind, value)` and a dict raised instead."""
        from src.menu_rules.unique_items_menu_rule import matches_declared
        s = self._solver({
            (WEEK[0], 'nonveg_main__2'): 'chicken_biryani',
            (WEEK[1], 'nonveg_main__2'): 'chicken_biryani',
        })
        declared = s._repeatable_declarations()
        row = pd.Series({'item': 'chicken_biryani'})
        assert matches_declared(row, 'nonveg_main', declared)
        assert not matches_declared(
            pd.Series({'item': 'egg_masala'}), 'nonveg_main', declared)

    def test_two_dishes_in_one_slot_are_both_declared(self):
        s = self._solver({
            (WEEK[0], 'nonveg_main__2'): 'chicken_biryani',
            (WEEK[1], 'nonveg_main__2'): 'chicken_biryani',
            (WEEK[0], 'nonveg_main__3'): 'boiled_egg',
            (WEEK[1], 'nonveg_main__3'): 'boiled_egg',
        })
        got = {m[0][1] for m in s._repeatable_declarations()['nonveg_main']}
        assert got == {'chicken_biryani', 'boiled_egg'}


class TestAPinThatCannotFitIsDropped:
    """Clamping an out-of-range pin onto the last expansion is a kindness for
    ONE pin. It stops being one the moment a second lands on the same cell.
    """

    @staticmethod
    def _cfg(counts):
        class Cfg:
            active_slots = [s for base, n in counts.items()
                            for s in ([base] if n == 1
                                      else [f'{base}__{i}'
                                            for i in range(1, n + 1)])]
            name = 'Counter 1'
        return Cfg()

    def test_one_out_of_range_pin_still_clamps(self):
        from src.application.constant_items import _resolve_constant_items
        resolved, _whole = _resolve_constant_items(
            'X', {'starter__2': 'Veg Kati Roll'}, self._cfg({'starter': 1}))
        assert resolved == {'starter': 'Veg Kati Roll'}

    def test_a_second_pin_onto_the_same_cell_is_dropped_not_stacked(self):
        """Three pins collapsing onto `nonveg_main__2` is three different
        dishes forced into one cell — INFEASIBLE, with nothing in the message
        pointing at the cause."""
        from src.application.constant_items import _resolve_constant_items
        resolved, _whole = _resolve_constant_items(
            'X',
            {'nonveg_main__2': 'Chicken Biryani',
             'nonveg_main__3': 'Boiled Egg',
             'nonveg_main__4': 'Bone Salna'},
            self._cfg({'nonveg_main': 2}))
        assert resolved == {'nonveg_main__2': 'Chicken Biryani'}

    def test_the_same_dish_twice_is_not_a_collision(self):
        from src.application.constant_items import _resolve_constant_items
        resolved, _whole = _resolve_constant_items(
            'X', {'nonveg_main__2': 'Same', 'nonveg_main__3': 'Same'},
            self._cfg({'nonveg_main': 2}))
        assert resolved == {'nonveg_main__2': 'Same'}
