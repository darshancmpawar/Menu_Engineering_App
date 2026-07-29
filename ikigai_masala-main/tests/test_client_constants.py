"""Tests for per-client constant_items overlay and working_days filtering."""

import datetime as dt

import pytest

from src.client.client_config import ClientConfig
from src.solver._helpers import cell_is_skipped
from src.solver.menu_solver import (
    SolverConfig,
    MenuSolver,
    _resolve_client_constant,
)
from api.app import (
    _filter_dates_by_working_days,
    _weekdays_from,
    _exclusive_siblings,
    _resolve_constant_items,
    _rules_and_skip_for_client,
)


class TestResolveClientConstant:
    def test_daily_string(self):
        assert _resolve_client_constant('buttermilk', 'monday') == 'buttermilk'
        assert _resolve_client_constant('buttermilk', 'friday') == 'buttermilk'

    def test_weekday_map_full_and_abbr(self):
        spec = {'friday': 'raita', 'wed': 'Curd'}
        assert _resolve_client_constant(spec, 'friday') == 'raita'
        assert _resolve_client_constant(spec, 'Wednesday') == 'Curd'
        assert _resolve_client_constant(spec, 'monday') is None

    def test_none_and_empty(self):
        assert _resolve_client_constant(None, 'monday') is None
        assert _resolve_client_constant({}, 'monday') is None


class TestWorkingDaysFilter:
    def test_filter_quince_week(self):
        mon = dt.date(2026, 3, 23)  # Monday
        week = _weekdays_from(mon, 5)
        filtered = _filter_dates_by_working_days(
            week, ['wednesday', 'thursday', 'friday'],
        )
        assert [d.strftime('%A') for d in filtered] == [
            'Wednesday', 'Thursday', 'Friday',
        ]

    def test_filter_none_unchanged(self):
        mon = dt.date(2026, 3, 23)
        week = _weekdays_from(mon, 5)
        assert _filter_dates_by_working_days(week, None) == week


class TestClientConstantItemsInPlan:
    def test_rows_to_week_plan_stamps_overlay(self):
        """Client constants land on the right days after global CONST_SLOTS."""
        dates = [
            dt.date(2026, 3, 25),  # Wednesday
            dt.date(2026, 3, 26),  # Thursday
            dt.date(2026, 3, 27),  # Friday
        ]
        cfg = SolverConfig(
            days=3,
            start_date=dates[0],
            explicit_dates=dates,
            active_base_slots=['rice'],
            const_slots=['papad'],
            client_constant_items={
                'curd': {'wednesday': 'Curd', 'thursday': 'Curd'},
                'curd_side': {'friday': 'raita'},
                'welcome_drink': 'buttermilk',
            },
        )
        solver = MenuSolver(pools={}, solver_config=cfg, menu_rules=[])
        chosen = {d: {} for d in dates}
        plan = solver._rows_to_week_plan(chosen, dates, expanded_slots=[])
        assert plan[dates[0]]['curd'] == 'Curd'
        assert plan[dates[0]]['welcome_drink'] == 'buttermilk'
        assert 'curd_side' not in plan[dates[0]]
        assert plan[dates[2]]['curd_side'] == 'raita'
        assert 'curd' not in plan[dates[2]]
        assert plan[dates[0]]['papad'] == 'Papad'


def _cfg(name, active_slots):
    """A minimal ClientConfig standing in for one counter."""
    return ClientConfig(name=name, active_slots=list(active_slots))


class TestExclusiveSiblings:
    def test_yogurt_pair_is_mutually_exclusive(self):
        assert _exclusive_siblings('curd') == {'curd_side'}
        assert _exclusive_siblings('curd_side') == {'curd'}

    def test_unrelated_slot_has_no_siblings(self):
        assert _exclusive_siblings('rice') == set()
        # curd_rice is independent of the yogurt pair.
        assert _exclusive_siblings('curd_rice') == set()


class TestResolveConstantItems:
    """Resolution against a single counter's served slots."""

    def test_drops_slot_the_counter_does_not_serve(self):
        """Amadeus' Chinese station serves rice + veg_gravy only, so the
        client-level salad/bread constants must not leak onto it."""
        resolved, whole = _resolve_constant_items(
            'Amadeus',
            {'salad': 'green salad', 'bread': 'plain chapati'},
            _cfg('Chinese', ['rice', 'veg_gravy']),
        )
        assert resolved == {}
        assert whole == set()

    def test_keeps_slot_the_counter_does_serve(self):
        resolved, whole = _resolve_constant_items(
            'Amadeus',
            {'salad': 'green salad', 'bread': 'plain chapati'},
            _cfg('South', ['bread', 'rice', 'salad', 'curd']),
        )
        assert resolved == {'salad': 'green salad', 'bread': 'plain chapati'}
        # Daily strings on single-expansion slots replace the slot outright.
        assert whole == {'salad', 'bread'}

    def test_keeps_constant_for_unserved_exclusive_sibling(self):
        """Booking.com serves curd_side, not curd, yet pins curd on four days:
        the pair is one logical yogurt slot so the constant is legitimate."""
        resolved, whole = _resolve_constant_items(
            'Booking.com',
            {'curd': {'monday': 'Curd'}, 'curd_side': {'wednesday': 'raita'}},
            _cfg('Counter 1', ['rice', 'curd_side']),
        )
        assert resolved == {
            'curd': {'monday': 'Curd'},
            'curd_side': {'wednesday': 'raita'},
        }
        assert whole == set()

    def test_unknown_slot_is_dropped_with_warning(self, caplog):
        import logging
        caplog.set_level(logging.WARNING, logger='api.app')
        resolved, _ = _resolve_constant_items(
            'Plan View', {'extra_item': 'boiled egg'},
            _cfg('Counter 1', ['rice', 'nonveg_main']),
        )
        assert resolved == {}
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert 'extra_item' in joined

    def test_bare_base_pins_last_expansion(self):
        """F5 pins nonveg_main on Wednesday and runs two nonveg slots: one
        must stay solvable, so the constant lands on __2."""
        resolved, whole = _resolve_constant_items(
            'F5', {'nonveg_main': {'wednesday': 'boiled egg'}},
            _cfg('Counter 1', ['rice', 'nonveg_main__1', 'nonveg_main__2']),
        )
        assert resolved == {'nonveg_main__2': {'wednesday': 'boiled egg'}}
        assert whole == set()

    def test_explicit_expansion_is_honoured(self):
        """Plan View pins nonveg_main__2 directly."""
        resolved, whole = _resolve_constant_items(
            'Plan View', {'nonveg_main__2': 'boiled egg'},
            _cfg('Counter 1', ['nonveg_main__1', 'nonveg_main__2']),
        )
        assert resolved == {'nonveg_main__2': 'boiled egg'}
        # Multi-expansion slot: the sibling cell is still solved.
        assert whole == set()

    def test_out_of_range_expansion_clamps(self, caplog):
        """A count reduction must not silently lose the constant."""
        import logging
        caplog.set_level(logging.WARNING, logger='api.app')
        resolved, _ = _resolve_constant_items(
            'Plan View', {'nonveg_main__2': 'boiled egg'},
            _cfg('Counter 1', ['nonveg_main']),
        )
        assert resolved == {'nonveg_main': 'boiled egg'}

    def test_no_client_cfg_keeps_registry_check_only(self):
        """Omitting client_cfg must not silently discard every constant."""
        resolved, whole = _resolve_constant_items(
            'X', {'salad': 'green salad', 'extra_item': 'nope'}, None,
        )
        assert resolved == {'salad': 'green salad'}
        assert whole == {'salad'}


class TestCellIsSkipped:
    D = dt.date(2026, 3, 25)

    def test_base_entry_skips_every_expansion(self):
        skips = {(self.D, 'nonveg_main')}
        assert cell_is_skipped(skips, self.D, 'nonveg_main__1')
        assert cell_is_skipped(skips, self.D, 'nonveg_main__2')

    def test_slot_id_entry_skips_only_that_expansion(self):
        skips = {(self.D, 'nonveg_main__2')}
        assert not cell_is_skipped(skips, self.D, 'nonveg_main__1')
        assert cell_is_skipped(skips, self.D, 'nonveg_main__2')

    def test_other_dates_unaffected(self):
        skips = {(self.D, 'curd')}
        assert not cell_is_skipped(skips, dt.date(2026, 3, 26), 'curd')


class TestSkipCellsSuppressSibling:
    """The regression that produced two yogurt rows a day for five clients."""

    @pytest.fixture(autouse=True)
    def _stub_rules(self, monkeypatch):
        # Isolate constant handling from the city ruleset / Supabase.
        monkeypatch.setattr('api.app._get_menu_rules_for_city', lambda city: [])
        monkeypatch.setattr(
            'src.menu_rules.MenuRuleLoader.load_for_client',
            lambda self, name, generic, counter_name=None: [],
        )

    def _skips(self, monkeypatch, constants, active_slots, dates):
        monkeypatch.setattr(
            'src.menu_rules.MenuRuleLoader.get_client_constant_items',
            lambda self, name, counter_name=None: constants,
        )
        _rules, skips, resolved, whole, forced = _rules_and_skip_for_client(
            'Booking.com', dates, city='bangalore',
            client_cfg=_cfg('Counter 1', active_slots),
        )
        # A pin naming a real ontology dish is solved (its cell is narrowed to
        # that dish) rather than skipped; either way the cell is accounted for,
        # so tests that care about "this slot is not left free" check both.
        self._forced = forced
        return skips, resolved, whole

    def test_curd_constant_suppresses_curd_side_cell(self, monkeypatch):
        mon = dt.date(2026, 3, 23)
        dates = _weekdays_from(mon, 5)          # Mon..Fri
        wed = dates[2]
        skips, resolved, _ = self._skips(
            monkeypatch,
            {'curd': {'monday': 'Curd', 'tuesday': 'Curd',
                      'thursday': 'Curd', 'friday': 'Curd'},
             'curd_side': {'wednesday': 'raita'}},
            ['rice', 'curd_side'],
            dates,
        )
        assert set(resolved) == {'curd', 'curd_side'}
        # Every day pins exactly one of the pair, so no curd_side is ever left
        # free to be chosen. A pin naming a real dish is honoured by narrowing
        # its cell to that dish (forced) instead of skipping it, so "not free"
        # means skipped OR forced.
        for d in dates:
            accounted = (
                cell_is_skipped(skips, d, 'curd_side')
                or (d, 'curd_side') in self._forced
            )
            assert accounted, d
        # Wednesday pins the raita itself — 'raita' is a real ontology dish, so
        # that cell is solved-and-pinned rather than stamped.
        assert (wed, 'curd_side') in self._forced
        assert (wed, 'curd') in skips, 'the curd sibling must still be removed'
        # The other days pin curd, which removes the curd_side cell outright.
        assert cell_is_skipped(skips, dates[0], 'curd_side')

    def test_unconstrained_day_still_solves_the_slot(self, monkeypatch):
        """Quince pins curd Wed/Thu and raita Fri — Mon/Tue stay solvable."""
        mon = dt.date(2026, 3, 23)
        dates = _weekdays_from(mon, 5)
        skips, _resolved, _ = self._skips(
            monkeypatch,
            {'curd': {'wednesday': 'Curd', 'thursday': 'Curd'},
             'curd_side': {'friday': 'raita'}},
            ['rice', 'curd'],
            dates,
        )
        def pinned(d):
            return (cell_is_skipped(skips, d, 'curd')
                    or (d, 'curd') in self._forced)

        assert not pinned(dates[0])   # Monday free to solve
        assert not pinned(dates[1])   # Tuesday free to solve
        # 'Curd' is a real ontology dish, so Wed/Thu are solved-and-pinned.
        assert (dates[2], 'curd') in self._forced
        assert (dates[3], 'curd') in self._forced
        # Friday pins raita, which must remove the curd cell entirely.
        assert cell_is_skipped(skips, dates[4], 'curd')

    def test_multi_expansion_pin_leaves_sibling_solvable(self, monkeypatch):
        mon = dt.date(2026, 3, 23)
        dates = _weekdays_from(mon, 5)
        wed = dates[2]
        skips, resolved, _ = self._skips(
            monkeypatch,
            {'nonveg_main': {'wednesday': 'boiled egg'}},
            ['nonveg_main__1', 'nonveg_main__2'],
            dates,
        )
        assert set(resolved) == {'nonveg_main__2'}
        assert cell_is_skipped(skips, wed, 'nonveg_main__2')
        assert not cell_is_skipped(skips, wed, 'nonveg_main__1')
