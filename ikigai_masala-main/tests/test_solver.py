"""
End-to-end smoke test for ``MenuSolver``.

Exercises the full pipeline — real Excel ontology → pool build → CP-SAT
solve — without Supabase or Flask. Verifies that a minimal one-day plan
can be produced and that each slot is filled exactly once.
"""

from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("pandas", reason="pandas not installed")
pytest.importorskip("ortools", reason="ortools not installed")

from src.preprocessor import ExcelReader, DataCleanser
from src.preprocessor.pool_builder import PoolBuilder
from src.solver.menu_solver import MenuSolver, SolverConfig


@pytest.fixture(scope="module")
def cleaned_menu(ensure_sample_data_exists):
    reader = ExcelReader(str(ensure_sample_data_exists))
    raw = reader.read()
    return DataCleanser(raw).clean()


@pytest.fixture(scope="module")
def pools(cleaned_menu):
    return PoolBuilder.build_pools(cleaned_menu)


def test_solver_produces_single_day_plan(cleaned_menu, pools):
    """Solver returns a plan covering every active slot exactly once."""
    active = [
        'welcome_drink', 'starter', 'soup', 'salad',
        'rice', 'dal', 'veg_gravy', 'veg_dry', 'bread',
        'curd_side', 'dessert',
    ]
    cfg = SolverConfig(
        days=1,
        start_date=dt.date(2026, 3, 23),  # Monday
        time_limit_sec=60,
        active_base_slots=active,
        slot_counts={s: 1 for s in active},
    )

    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=[])
    plan, dates = solver.solve()

    assert len(dates) == 1
    day_map = plan[dates[0]]
    for slot in active:
        assert slot in day_map, f"missing slot: {slot}"
        assert day_map[slot], f"empty item for slot: {slot}"


def test_soft_rule_failures_are_captured_not_silent(cleaned_menu, pools):
    """A soft rule whose get_objective_terms() raises must surface in
    solver.rule_failures with the rule name + exception details, rather
    than being silently swallowed."""
    from src.menu_rules.base_menu_rule import BaseMenuRule, MenuRuleSeverity

    class _BrokenSoftRule(BaseMenuRule):
        severity = MenuRuleSeverity.SOFT

        def __init__(self):
            super().__init__({'name': 'broken_soft'})

        def apply(self, *_a, **_kw):
            return

        def get_objective_terms(self, *_a, **_kw):
            raise ValueError("broken weighting config")

    active = [
        'welcome_drink', 'starter', 'soup', 'salad',
        'rice', 'dal', 'veg_gravy', 'veg_dry', 'bread',
        'curd_side', 'dessert',
    ]
    cfg = SolverConfig(
        days=1,
        start_date=dt.date(2026, 3, 23),
        time_limit_sec=60,
        active_base_slots=active,
        slot_counts={s: 1 for s in active},
    )

    solver = MenuSolver(
        pools=pools, solver_config=cfg, menu_rules=[_BrokenSoftRule()],
    )
    plan, _ = solver.solve()

    # Plan still produced — the broken rule is soft, so it's dropped.
    assert plan, "soft-rule failure should not block the solve"
    # ...but we must have a record so an admin knows the rule was skipped.
    assert solver.rule_failures, "broken soft rule should be recorded"
    entry = solver.rule_failures[0]
    assert entry['rule'] == 'broken_soft'
    assert entry['phase'] == 'get_objective_terms'
    assert 'ValueError' in entry['error']
    assert 'broken weighting config' in entry['error']
