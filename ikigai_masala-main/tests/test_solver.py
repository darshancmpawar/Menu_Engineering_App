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
