"""
Soft freshness / menu-variety objective.

A dish's hard cooldown (default 20 days) only *bans* an item for a window; once
it lapses nothing stops the solver reprinting day-1's menu on day 21. The soft
freshness objective closes that gap: among eligible candidates it prefers the
one served longest ago (or never), so plans spread item usage over time. It is
a preference only — it never bans, so it can never make a solve INFEASIBLE, and
any real rule still outranks it.

Covered here:
  * HistoryManager.days_since_last_served — the recency map from history.
  * MenuSolver._freshness_bonus — the per-candidate weight + its bounds.
  * An end-to-end solve: the least-recently-served candidate wins an otherwise
    unconstrained cell, and freshness never forces INFEASIBLE.
"""

from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("pandas", reason="pandas not installed")
pytest.importorskip("ortools", reason="ortools not installed")

import pandas as pd

from src.history.history_manager import HistoryManager
from src.preprocessor import ExcelReader, DataCleanser
from src.preprocessor.column_mapper import _norm_str
from src.preprocessor.pool_builder import PoolBuilder
from src.solver._helpers import strip_color_suffix
from src.solver.menu_solver import (
    MenuSolver, SolverConfig, FRESHNESS_CAP_DAYS, FRESHNESS_UNIT,
)


# --- HistoryManager.days_since_last_served ---------------------------------

def _hm(rows):
    hm = HistoryManager()
    hm.load_from_dataframes(pd.DataFrame(rows), None)
    return hm


def test_days_since_counts_from_as_of():
    hm = _hm([
        {'client_name': 'c', 'service_date': '2026-08-01', 'slot': 'dal',
         'item_base': 'dal_tadka'},
        {'client_name': 'c', 'service_date': '2026-07-20', 'slot': 'dal',
         'item_base': 'dal_tadka'},  # older duplicate ignored (max wins)
        {'client_name': 'c', 'service_date': '2026-07-25', 'slot': 'veg_dry',
         'item_base': 'aloo_jeera'},
    ])
    m = hm.days_since_last_served(dt.date(2026, 8, 11))
    assert m['dal_tadka'] == 10   # 2026-08-01 → 2026-08-11
    assert m['aloo_jeera'] == 17  # 2026-07-25 → 2026-08-11


def test_days_since_ignores_future_and_same_day():
    hm = _hm([
        {'client_name': 'c', 'service_date': '2026-08-11', 'slot': 'dal',
         'item_base': 'today_dish'},   # == as_of, excluded (strictly before)
        {'client_name': 'c', 'service_date': '2026-08-20', 'slot': 'dal',
         'item_base': 'future_dish'},  # after as_of, excluded
        {'client_name': 'c', 'service_date': '2026-08-05', 'slot': 'dal',
         'item_base': 'past_dish'},
    ])
    m = hm.days_since_last_served(dt.date(2026, 8, 11))
    assert 'today_dish' not in m
    assert 'future_dish' not in m
    assert m['past_dish'] == 6


def test_days_since_excludes_staples():
    hm = _hm([
        {'client_name': 'c', 'service_date': '2026-08-05', 'slot': 'curd',
         'item_base': 'plain_curd'},
        {'client_name': 'c', 'service_date': '2026-08-05', 'slot': 'dal',
         'item_base': 'steamed_rice'},
    ])
    m = hm.days_since_last_served(
        dt.date(2026, 8, 11),
        const_slots=['curd'],
        repeatable_items={'steamed_rice'},
    )
    assert 'plain_curd' not in m       # const slot excluded
    assert 'steamed_rice' not in m     # repeatable item excluded


def test_days_since_empty_history_is_empty():
    hm = HistoryManager()
    assert hm.days_since_last_served(dt.date(2026, 8, 11)) == {}


# --- MenuSolver._freshness_bonus -------------------------------------------

def _solver_with_recency(recency):
    cfg = SolverConfig(days=1, start_date=dt.date(2026, 3, 23),
                       active_base_slots=['dal'], slot_counts={'dal': 1})
    return MenuSolver(pools={}, solver_config=cfg, menu_rules=[],
                      recency_by_item=recency)


def test_freshness_bonus_never_served_is_capped_max():
    s = _solver_with_recency({'x': 5})
    # 'y' absent from the map → maximally fresh → full cap.
    assert s._freshness_bonus('y') == FRESHNESS_CAP_DAYS * FRESHNESS_UNIT


def test_freshness_bonus_recent_is_low():
    s = _solver_with_recency({'dal_tadka': 2})
    assert s._freshness_bonus('dal_tadka') == 2 * FRESHNESS_UNIT


def test_freshness_bonus_is_capped():
    s = _solver_with_recency({'ancient': 999})
    assert s._freshness_bonus('ancient') == FRESHNESS_CAP_DAYS * FRESHNESS_UNIT


def test_freshness_bonus_disabled_without_map():
    s = _solver_with_recency({})   # no recency supplied
    assert s._freshness_bonus('anything') == 0


def test_freshness_bonus_stays_below_low_tier():
    """One LOW-tier soft-rule unit (1e6) must outrank the biggest freshness
    bonus, so a real rule always wins a cell over freshness."""
    from src.constants import OBJECTIVE_TIER_WEIGHTS
    assert FRESHNESS_CAP_DAYS * FRESHNESS_UNIT < OBJECTIVE_TIER_WEIGHTS['low']
    # ... and one day of freshness must beat the random tie-break (max ~1000).
    assert FRESHNESS_UNIT > 1000


class TestRegenerateOutbidsFreshness:
    """The regenerate penalty and the freshness bonus pull on the SAME dish.

    `MenuRegenerator` falls back to a penalty when hard-forbidding the old dish
    would empty the cell. The dish it is penalising is usually the one freshness
    likes most: a dish absent from the recency map scores the full cap, and
    absent is the common case, since the map holds only what has been saved to
    history. At -10_000 against a +90_000 cap the penalty lost by 9:1 and the
    solver re-picked the dish the user had just asked to replace — the button
    appeared to do nothing.

    Pinned as an ORDERING between the two constants rather than as literals, so
    tuning either one cannot quietly re-open it.
    """

    def test_the_penalty_outbids_the_biggest_freshness_bonus(self):
        from src.solver.menu_solver import (
            MAX_FRESHNESS_BONUS, REGEN_SIMILARITY_PENALTY,
        )
        assert abs(REGEN_SIMILARITY_PENALTY) > MAX_FRESHNESS_BONUS

    def test_it_outbids_it_by_a_margin_not_a_hair(self):
        """A one-unit margin would be decided by the random tie-break."""
        from src.solver.menu_solver import (
            FRESHNESS_UNIT, MAX_FRESHNESS_BONUS, REGEN_SIMILARITY_PENALTY,
        )
        head = abs(REGEN_SIMILARITY_PENALTY) - MAX_FRESHNESS_BONUS
        assert head > FRESHNESS_UNIT * FRESHNESS_CAP_DAYS

    def test_it_still_sits_under_one_low_tier_rule_unit(self):
        """A regenerate is the user's request, not a licence to overrule the
        rules: a soft preference must still be able to keep a dish in place."""
        from src.constants import OBJECTIVE_TIER_WEIGHTS
        from src.solver.menu_solver import REGEN_SIMILARITY_PENALTY
        assert abs(REGEN_SIMILARITY_PENALTY) < OBJECTIVE_TIER_WEIGHTS['low']

    def test_the_cap_constant_matches_the_bonus_it_names(self):
        from src.solver.menu_solver import MAX_FRESHNESS_BONUS
        assert MAX_FRESHNESS_BONUS == FRESHNESS_CAP_DAYS * FRESHNESS_UNIT


# --- end-to-end: least-recently-served candidate wins ----------------------

@pytest.fixture(scope="module")
def pools(ensure_sample_data_exists):
    raw = ExcelReader(str(ensure_sample_data_exists)).read()
    cleaned = DataCleanser(raw).clean()
    return PoolBuilder.build_pools(cleaned)


def test_solver_prefers_least_recently_served(pools):
    """With every dal candidate marked recently served except one, the solver
    must pick that one — freshness dominates the random tie-break."""
    dal_items = [str(v) for v in pools['dal']['item'].tolist()]
    assert len(dal_items) >= 3, "need a few candidates to make the pick meaningful"

    target = dal_items[len(dal_items) // 2]
    # Everything served today (score 0) except the target, served long ago.
    recency = {_norm_str(name): 0 for name in dal_items}
    recency[_norm_str(target)] = FRESHNESS_CAP_DAYS

    cfg = SolverConfig(days=1, start_date=dt.date(2026, 3, 23),
                       active_base_slots=['dal'], slot_counts={'dal': 1})
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=[],
                        recency_by_item=recency)
    plan, dates = solver.solve()

    picked = _norm_str(strip_color_suffix(plan[dates[0]]['dal']))
    assert picked == _norm_str(target), (
        f"expected freshest dal {target!r}, got {picked!r}"
    )


def test_freshness_never_forces_infeasible(pools):
    """A recency map that marks every candidate recently served must not make
    the solve fail — freshness only shapes the objective."""
    active = ['rice', 'dal', 'veg_gravy', 'veg_dry', 'bread']
    recency = {}
    for slot in active:
        for name in pools[slot]['item'].tolist():
            recency[_norm_str(name)] = 0   # all "just served"
    cfg = SolverConfig(days=1, start_date=dt.date(2026, 3, 23),
                       active_base_slots=active,
                       slot_counts={s: 1 for s in active})
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=[],
                        recency_by_item=recency)
    plan, dates = solver.solve()
    for slot in active:
        assert plan[dates[0]].get(slot), f"slot {slot} unexpectedly empty"
