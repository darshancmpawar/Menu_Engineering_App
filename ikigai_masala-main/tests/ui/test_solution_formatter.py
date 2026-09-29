"""Tests for SolutionFormatter."""

import datetime as dt

import pytest

from src.solver.solution_formatter import SolutionFormatter


@pytest.fixture
def sample_plan():
    """A minimal week plan with 2 days and 3 slots each."""
    d1 = dt.date(2026, 3, 23)  # Monday
    d2 = dt.date(2026, 3, 24)  # Tuesday
    plan = {
        d1: {
            'welcome_drink': 'mango lassi(Y)',
            'rice': 'jeera rice(Y)',
            'dal': 'dal makhani(R)',
        },
        d2: {
            'welcome_drink': 'mint lemonade(G)',
            'rice': 'fried rice(Y)',
            'dal': 'sambar(R)',
        },
    }
    return plan, [d1, d2]


class TestSolutionFormatter:
    def test_init(self, sample_plan):
        plan, dates = sample_plan
        f = SolutionFormatter(plan, dates)
        assert f.week_plan == plan
        assert f.dates == dates

    def test_to_dict(self, sample_plan):
        plan, dates = sample_plan
        f = SolutionFormatter(plan, dates)
        d = f.to_dict()
        assert '2026-03-23' in d
        assert '2026-03-24' in d
        assert d['2026-03-23']['day_type'] == 'mix'
        assert d['2026-03-24']['day_type'] == 'chinese'
        assert d['2026-03-23']['items']['rice']['item'] == 'jeera rice(Y)'
        assert d['2026-03-23']['items']['rice']['item_base'] == 'jeera rice'

    def test_empty_plan(self):
        f = SolutionFormatter({}, [])
        d = f.to_dict()
        assert d == {}

    def test_is_nonveg_flag(self):
        d1 = dt.date(2026, 3, 23)
        plan = {d1: {'nonveg_main': 'chicken_65(R)', 'rice': 'jeera rice(Y)'}}
        f = SolutionFormatter(plan, [d1], nonveg_items={'chicken_65'})
        out = f.to_dict()['2026-03-23']['items']
        assert out['nonveg_main']['is_nonveg'] is True
        assert out['rice']['is_nonveg'] is False

    def test_is_nonveg_defaults_false_without_lookup(self, sample_plan):
        plan, dates = sample_plan
        out = SolutionFormatter(plan, dates).to_dict()
        assert out['2026-03-23']['items']['rice']['is_nonveg'] is False

    def test_is_pinned_is_per_cell_not_per_slot(self, sample_plan):
        """A Monday-only pin must not mark Tuesday's cell of the same slot —
        the table's pin marker is what tells a planner which dishes the solver
        was free to choose, and a wrong one sends them looking for a rule that
        does not exist."""
        plan, dates = sample_plan
        out = SolutionFormatter(
            plan, dates, pinned_cells={(dates[0], 'rice')}).to_dict()
        assert out['2026-03-23']['items']['rice']['is_pinned'] is True
        assert out['2026-03-24']['items']['rice']['is_pinned'] is False
        assert out['2026-03-23']['items']['dal']['is_pinned'] is False

    def test_is_pinned_defaults_false_when_not_reported(self, sample_plan):
        """A replayed saved plan passes nothing: no markers, not "nothing is
        pinned" — the two look the same on screen and only one is a claim."""
        plan, dates = sample_plan
        out = SolutionFormatter(plan, dates).to_dict()
        assert out['2026-03-23']['items']['rice']['is_pinned'] is False
