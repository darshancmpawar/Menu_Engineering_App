"""Tests for SolutionFormatter."""

import datetime as dt
import os
import tempfile

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

    def test_print_summary(self, sample_plan, capsys):
        plan, dates = sample_plan
        f = SolutionFormatter(plan, dates)
        f.print_summary()
        captured = capsys.readouterr()
        assert 'MENU PLAN SOLUTION' in captured.out
        assert '2 days' in captured.out
        assert '2026-03-23' in captured.out

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

    def test_to_csv(self, sample_plan, tmp_path):
        plan, dates = sample_plan
        f = SolutionFormatter(plan, dates)
        csv_path = str(tmp_path / 'test_plan.csv')
        f.to_csv(csv_path)
        assert os.path.exists(csv_path)
        with open(csv_path) as fh:
            lines = fh.readlines()
        assert len(lines) == 4  # header + 3 slots

    def test_to_excel(self, sample_plan, tmp_path):
        plan, dates = sample_plan
        f = SolutionFormatter(plan, dates)
        xlsx_path = str(tmp_path / 'test_plan.xlsx')
        f.to_excel(xlsx_path)
        assert os.path.exists(xlsx_path)

    def test_empty_plan(self):
        f = SolutionFormatter({}, [])
        d = f.to_dict()
        assert d == {}

    def test_to_csv_empty(self, tmp_path):
        f = SolutionFormatter({}, [])
        csv_path = str(tmp_path / 'empty.csv')
        f.to_csv(csv_path)
        # File should not be created for empty plan
        assert not os.path.exists(csv_path)
