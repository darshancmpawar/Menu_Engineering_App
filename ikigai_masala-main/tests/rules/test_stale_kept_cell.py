"""A regenerate keeps every cell it is not asked to replace. When one of those
kept dishes is one today's rules filter out (a week saved before a rule
changed), no plan exists, and the error has to say which cell, or the operator
is left hunting for a rule conflict (Rippling, 23 Nov dinner, 18 Nov)."""
from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("pandas", reason="pandas not installed")
pytest.importorskip("ortools", reason="ortools not installed")

from src.preprocessor import DataCleanser, ExcelReader
from src.preprocessor.pool_builder import PoolBuilder
from src.solver.menu_solver import MenuSolver, SolverConfig

MONDAY = dt.date(2026, 3, 23)


@pytest.fixture(scope="module")
def pools(ensure_sample_data_exists):
    raw = ExcelReader(str(ensure_sample_data_exists)).read()
    return PoolBuilder.build_pools(DataCleanser(raw).clean())


def test_a_kept_dish_the_rules_filter_out_is_named(pools):
    cfg = SolverConfig(days=1, start_date=MONDAY,
                       active_base_slots=['dal', 'rice'],
                       slot_counts={'dal': 1, 'rice': 1})
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=[])
    kept_rice = str(pools['rice']['item'].iloc[0])
    with pytest.raises(RuntimeError) as err:
        solver.solve(locked={(MONDAY, 'dal'): 'mixed_curd',
                             (MONDAY, 'rice'): kept_rice})
    msg = str(err.value)
    assert "2026-03-23 dal 'mixed_curd'" in msg
    assert "Generate the week again" in msg
    assert kept_rice not in msg, "a kept dish that IS allowed is not stale"
