"""A cadence is two rules: not twice inside the window, and not never.

`selector_history_window` was only ever the first half. "Khichdi once in three
weeks" written as a ban alone is satisfied by serving no khichdi at all — the
dish can disappear for months while the rule reads as enforced, which is the
sprouts-gravy defect of v2.07.01 (a cap written where a floor was asked for)
in a second place.

`at_least_once_per_window` is the other half, and it is opt-in: thirteen of
the fourteen windows in the fleet are caps and stay caps.

The floor is the only part of this rule that is a CP-SAT constraint. A ban
removes candidates; a floor demands one, so it cannot be precomputed into
`banned_by_date` the way the ceiling is. That asymmetry is where the two
failure modes below live.
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.menu_rules.relaxations import RELAXATION
from src.menu_rules.selector_history_window_rule import SelectorHistoryWindowRule

WINDOW = 21
FAMILY = {'dal_khichdi', 'moong_khichadi', 'masala_khichadi'}


def _rule(**extra):
    cfg = {'type': 'selector_history_window', 'name': 'khichdi_21d',
           'selector': {'sub_category': 'north_khichdi'}, 'base_slot': 'rice',
           'window_days': WINDOW, 'at_least_once_per_window': True}
    cfg.update(extra)
    r = SelectorHistoryWindowRule(cfg)
    r.resolved_items = set(FAMILY)
    return r


class _Cell:
    """The slice of the solver's cell that `apply()` actually touches."""

    def __init__(self, model, base_slot, items, subs):
        self.base_slot = base_slot
        self.x_vars = [model.NewBoolVar(i) for i in items]
        self.cand_rows = [pd.Series({'item': i, 'sub_category': s})
                          for i, s in zip(items, subs)]
        model.AddExactlyOne(self.x_vars)


def _solve(rule, recency, *, rice_items=None, days=3):
    """Build a tiny model, apply the rule, solve, return the chosen rices."""
    rice_items = rice_items or ['dal_khichdi', 'jeera_rice', 'ghee_rice']
    subs = ['north_khichdi' if i in FAMILY else 'north_flavoured'
            for i in rice_items]
    model = cp_model.CpModel()
    cells = [_Cell(model, 'rice', rice_items, subs) for _ in range(days)]
    ctx = {'cells': cells,
           'dates': [dt.date(2026, 8, 3) + dt.timedelta(days=i)
                     for i in range(days)],
           'recency_by_item': recency}
    rule.apply(model, {}, None, ctx)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return [next(i for v, i in zip(c.x_vars, rice_items) if solver.Value(v))
            for c in cells]


class TestTheFloorFires:
    def test_a_family_never_served_is_overdue(self):
        """An EMPTY recency map does not mean "fresh" here, which is how the
        freshness objective reads the same map. A dish absent from it was not
        served inside the queried window, and for a cadence that is overdue."""
        assert any(r in FAMILY for r in _solve(_rule(), {}))

    def test_a_family_served_longer_ago_than_the_window_is_overdue(self):
        assert any(r in FAMILY for r in _solve(_rule(), {'dal_khichdi': 21}))

    def test_a_family_served_inside_the_window_is_not_forced(self):
        """The guard against the implementation's own worst failure: if the
        resolved family never reached the rule, every plan would read "never
        served" and serve a khichdi every week.

        Asserted on the CONSTRAINT rather than on the solution, because a
        solver left free may still pick a khichdi — "it did not appear" would
        pass for the wrong reason."""
        model = cp_model.CpModel()
        cells = [_Cell(model, 'rice', ['dal_khichdi', 'jeera_rice'],
                       ['north_khichdi', 'north_flavoured'])]
        before = len(model.Proto().constraints)
        _rule().apply(model, {}, None, {
            'cells': cells, 'dates': [dt.date(2026, 8, 3)],
            'recency_by_item': {'dal_khichdi': 5}})
        assert len(model.Proto().constraints) == before

    def test_the_clock_is_the_most_recent_member_not_the_oldest(self):
        """A khichdi five days ago makes the FAMILY five days old, even if a
        different khichdi last ran a year back. `min`, not `max`."""
        recency = {'dal_khichdi': 400, 'moong_khichadi': 5}
        model = cp_model.CpModel()
        cells = [_Cell(model, 'rice', ['dal_khichdi', 'jeera_rice'],
                       ['north_khichdi', 'north_flavoured'])]
        before = len(model.Proto().constraints)
        _rule().apply(model, {}, None, {
            'cells': cells, 'dates': [dt.date(2026, 8, 3)],
            'recency_by_item': recency})
        assert len(model.Proto().constraints) == before


class TestItStaysOutOfTheWayOtherwise:
    def test_a_window_without_the_flag_adds_nothing(self):
        """Thirteen of the fourteen windows in the fleet are caps."""
        model = cp_model.CpModel()
        cells = [_Cell(model, 'rice', ['dal_khichdi', 'jeera_rice'],
                       ['north_khichdi', 'north_flavoured'])]
        before = len(model.Proto().constraints)
        _rule(at_least_once_per_window=False).apply(model, {}, None, {
            'cells': cells, 'dates': [dt.date(2026, 8, 3)],
            'recency_by_item': {}})
        assert len(model.Proto().constraints) == before

    def test_another_slot_does_not_satisfy_the_floor(self):
        """`base_slot` scopes the floor. A khichdi arriving in some other slot
        would satisfy it on paper and leave the rice slot without one."""
        model = cp_model.CpModel()
        cells = [_Cell(model, 'healthy_rice', ['dal_khichdi', 'jeera_rice'],
                       ['north_khichdi', 'north_flavoured'])]
        before = len(model.Proto().constraints)
        _rule().apply(model, {}, None, {
            'cells': cells, 'dates': [dt.date(2026, 8, 3)],
            'recency_by_item': {}})
        assert len(model.Proto().constraints) == before


class TestItDegradesRatherThanFailing:
    def test_due_with_nothing_to_serve_stands_down_and_says_so(self, caplog):
        """Every khichdi cooled down is the ordinary case, not an error: the
        ceiling's own ban empties the family for the whole window. A menu must
        still come out, and the explanation must name the cadence that did not
        hold (note 31)."""
        model = cp_model.CpModel()
        cells = [_Cell(model, 'rice', ['jeera_rice', 'ghee_rice'],
                       ['north_flavoured', 'north_flavoured'])]
        with caplog.at_level(logging.INFO, logger='src.menu_rules'):
            _rule().apply(model, {}, None, {
                'cells': cells, 'dates': [dt.date(2026, 8, 3)],
                'recency_by_item': {}})
        stamped = [r for r in caplog.records if getattr(r, RELAXATION, None)]
        assert [getattr(r, RELAXATION) for r in stamped] == ['khichdi_21d']
        assert stamped[0].name == 'src.menu_rules.selector_history_window_rule'

    def test_nothing_is_stamped_when_the_floor_was_not_due(self, caplog):
        """The bug this caught in its own first draft: the availability check
        ran BEFORE the clock, so the week after a khichdi — when the ceiling
        has correctly emptied the family — logged a relaxation for a rule that
        was asking for nothing. A channel that fires when a rule is satisfied
        means two things and is worth less than silence."""
        model = cp_model.CpModel()
        cells = [_Cell(model, 'rice', ['jeera_rice', 'ghee_rice'],
                       ['north_flavoured', 'north_flavoured'])]
        with caplog.at_level(logging.INFO, logger='src.menu_rules'):
            _rule().apply(model, {}, None, {
                'cells': cells, 'dates': [dt.date(2026, 8, 3)],
                'recency_by_item': {'dal_khichdi': 5}})
        assert not [r for r in caplog.records if getattr(r, RELAXATION, None)]


class TestTheConfigIsRejectedEarlyWhenItCannotWork:
    def test_a_floor_without_a_base_slot_is_a_config_error(self):
        errs = SelectorHistoryWindowRule({
            'type': 'selector_history_window', 'name': 'x',
            'selector': {'flag': 'is_leafy_based_dish'}, 'window_days': 15,
            'at_least_once_per_window': True}).validation_errors()
        assert any('base_slot' in e for e in errs), errs

    def test_a_cap_without_a_base_slot_is_still_fine(self):
        assert SelectorHistoryWindowRule({
            'type': 'selector_history_window', 'name': 'x',
            'selector': {'flag': 'is_leafy_based_dish'},
            'window_days': 15}).validation_errors() == []


def test_the_input_layer_hands_the_family_to_the_rule():
    """`apply()` is given no ontology frame, so the floor cannot resolve its
    own selector — `prepare_solver_inputs` sets `resolved_items` at the moment
    it resolves the ban. If that line is ever dropped the family reads as empty,
    which reads as "never served", and the dish is forced into EVERY plan.
    """
    import inspect
    from src.application import solve_inputs
    src = inspect.getsource(solve_inputs.prepare_solver_inputs)
    assert 'r.resolved_items = r.matching_items(df)' in src


if __name__ == '__main__':      # a runnable check without pytest
    raise SystemExit(pytest.main([__file__, '-q']))
