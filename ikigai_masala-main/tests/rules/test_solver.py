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


def test_small_counter_generates_despite_color_min(cleaned_menu, pools):
    """A counter with fewer colour-slots than min_distinct_colors_per_day
    (e.g. a Chinese station of just rice + veg_gravy) must still generate —
    the colour-variety minimum is clamped to the number of colour slots
    rather than making the day INFEASIBLE. Regression for the multi-counter
    'Chinese counter produces no menu' bug."""
    slots = ['rice', 'veg_gravy']
    theme_map = {d: 'chinese' for d in
                 ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')}
    cfg = SolverConfig(
        days=5,
        start_date=dt.date(2026, 3, 23),
        time_limit_sec=30,
        active_base_slots=slots,
        slot_counts={s: 1 for s in slots},
        theme_map=theme_map,
        const_slots=[],
    )
    # default min_distinct_colors_per_day is 4 > 2 available colour slots.
    assert cfg.min_distinct_colors_per_day == 4
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=[])
    plan, dates = solver.solve()
    assert len(dates) == 5
    for d in dates:
        assert plan[d].get('rice') and plan[d].get('veg_gravy')


def test_time_budget_is_a_total_not_per_attempt(pools, monkeypatch):
    """time_limit_sec is a TOTAL wall-clock budget. With a 60s request the
    multi-restart loop must not run 8 × 20s = 160s of solving; it stops once
    the budget is spent. Uses a fake clock so no real time passes."""
    import src.solver.menu_solver as ms

    clock = {"t": 1000.0}
    monkeypatch.setattr(ms.time, "monotonic", lambda: clock["t"])

    attempts = []

    def _fake_solve(self, dates, cells, **kw):
        # Each attempt "consumes" its allotted time, then fails so the loop
        # keeps restarting until the deadline cuts it off.
        attempts.append(self.cfg.time_limit_sec)
        clock["t"] += self.cfg.time_limit_sec
        raise RuntimeError("forced failure (time limit)")

    monkeypatch.setattr(ms.MenuSolver, "_solve_cpsat", _fake_solve)
    monkeypatch.setattr(ms.MenuSolver, "_build_cells", lambda self, *a, **k: [])

    cfg = SolverConfig(days=1, start_date=dt.date(2026, 3, 23),
                       time_limit_sec=60, active_base_slots=['rice'],
                       slot_counts={'rice': 1})
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=[])
    with pytest.raises(RuntimeError):
        solver.solve()

    # 60s budget, 20s floor per attempt → at most 3 attempts, total <= 60s.
    assert sum(attempts) <= 60, f"burned {sum(attempts)}s > 60s budget: {attempts}"
    assert len(attempts) <= 3, f"ran {len(attempts)} attempts (pre-fix would run 8)"


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
    # Phase 3 #20: each failure carries the attempt_seed that produced
    # it so callers can tell which multi-restart iteration recorded it.
    assert isinstance(entry['attempt_seed'], int)


def test_soft_rule_typeerror_is_captured_not_crashing(cleaned_menu, pools):
    """The previous narrow ``except (ValueError, KeyError, AttributeError)``
    let any other exception type (TypeError, RuntimeError, ZeroDivisionError)
    escape and crash the whole solve — defeating the 'soft rules never
    block' contract. This test pins the broader Exception catch in place."""
    from src.menu_rules.base_menu_rule import BaseMenuRule, MenuRuleSeverity

    class _TypeErrorSoftRule(BaseMenuRule):
        severity = MenuRuleSeverity.SOFT

        def __init__(self):
            super().__init__({'name': 'te_soft'})

        def apply(self, *_a, **_kw):
            # Same unusual exception type in apply — previously uncaught.
            raise TypeError("wrong shape for apply")

        def get_objective_terms(self, *_a, **_kw):
            raise RuntimeError("weights not configured")

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
        pools=pools, solver_config=cfg, menu_rules=[_TypeErrorSoftRule()],
    )
    plan, _ = solver.solve()

    assert plan, "TypeError in a soft rule must not block the solve"
    phases = {(e['rule'], e['phase']) for e in solver.rule_failures}
    assert ('te_soft', 'apply') in phases
    assert ('te_soft', 'get_objective_terms') in phases
    # Error strings carry the class name so admins can triage.
    errors = " ".join(e['error'] for e in solver.rule_failures)
    assert 'TypeError' in errors
    assert 'RuntimeError' in errors


def test_hard_rule_typeerror_is_wrapped_as_runtimeerror(cleaned_menu, pools):
    """A HARD rule that raises any exception (including ones outside the
    old narrow tuple) must surface as a RuntimeError naming the rule."""
    from src.menu_rules.base_menu_rule import BaseMenuRule, MenuRuleSeverity

    class _HardTypeError(BaseMenuRule):
        severity = MenuRuleSeverity.HARD

        def __init__(self):
            super().__init__({'name': 'hard_te'})

        def apply(self, *_a, **_kw):
            raise TypeError("hard rule misconfigured")

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
        pools=pools, solver_config=cfg, menu_rules=[_HardTypeError()],
    )
    with pytest.raises(RuntimeError) as exc_info:
        solver.solve()
    # The multi-restart loop catches per-attempt RuntimeErrors and
    # re-raises a generic "no feasible plan" message, but chains the
    # root cause via ``from last_err``. Walk the chain to find our
    # hard-rule failure.
    chain = []
    err: BaseException | None = exc_info.value
    while err is not None:
        chain.append(str(err))
        err = err.__cause__
    joined = "\n".join(chain)
    assert "hard_te" in joined, f"expected rule name in cause chain, got:\n{joined}"
    assert "TypeError" in joined


def test_rule_failures_scoped_to_winning_attempt(cleaned_menu, pools):
    """Phase 3 #20 — failures from attempts that later raised
    RuntimeError must not appear in ``solver.rule_failures`` for the
    winning attempt. Previously they bled across because the list was
    only cleared once at the top of solve().

    Setup: a soft rule that records a failure on every attempt via
    get_objective_terms, plus a monkey-patch that makes the FIRST
    attempt fail (RuntimeError after the failure is recorded). The
    SECOND attempt succeeds. Assertion: rule_failures contains a
    single entry stamped with the *second* attempt's seed, not the
    first's."""
    from src.menu_rules.base_menu_rule import BaseMenuRule, MenuRuleSeverity

    class _MarkSeedSoftRule(BaseMenuRule):
        severity = MenuRuleSeverity.SOFT

        def __init__(self):
            super().__init__({'name': 'seed_marker'})

        def apply(self, *_a, **_kw):
            return

        def get_objective_terms(self, *_a, **_kw):
            # Always fails so every attempt records one entry.
            raise ValueError("always fails")

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
        pools=pools, solver_config=cfg, menu_rules=[_MarkSeedSoftRule()],
    )

    # Force the first attempt to fail AFTER the rule has recorded its
    # failure — this is exactly the "lost during retry" scenario.
    call_count = {'n': 0}
    real_solve_cpsat = solver._solve_cpsat

    def _fail_first_call(*args, **kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            raise RuntimeError("forced first-attempt failure")
        return real_solve_cpsat(*args, **kwargs)

    solver._solve_cpsat = _fail_first_call

    plan, _ = solver.solve()

    # Sanity: the plan came from attempt 2+ (solver retried after our
    # forced failure), so rule_failures has exactly one entry tagged
    # with attempt 2's seed — NOT the first attempt's residue.
    assert plan, "solver should have succeeded on the retry"
    assert call_count['n'] >= 2, "first attempt must have failed and retried"
    assert len(solver.rule_failures) == 1, (
        "rule_failures from failed attempts must be cleared; got "
        f"{solver.rule_failures}"
    )
    entry = solver.rule_failures[0]
    assert entry['rule'] == 'seed_marker'
    # Winning attempt's seed is the non-first one (larger by the
    # DEFAULT_SEED_RESTART_STEP=17 increment).
    assert entry['attempt_seed'] is not None
    assert entry['attempt_seed'] != cfg.seed, (
        f"expected winning attempt's stamped seed != base {cfg.seed}, "
        f"got {entry['attempt_seed']}"
    )
