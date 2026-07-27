"""End-to-end integration test — real Excel, real rules, multi-day solve.

This is the one test in the suite that exercises the full pipeline the
way the API does: Excel ontology -> pool build -> CP-SAT with every
rule from the production config -> extracted plan. It's marked ``slow``
because a 5-day solve with the full ruleset takes 20-60s depending on
the host. PR CI skips it by default; the nightly / manual workflow
runs it.

What it proves that the unit tests don't:
  * The real rule config in ``data/configs/city_rules/bangalore.json``
    loads without warnings.
  * Those rules, together, produce a feasible plan on the bundled
    ontology — no silent pool exhaustion, no INFEASIBLE from conflicting
    pre-filters.
  * Every active slot is filled on every day.
  * No rule ends up on ``solver.rule_failures`` (soft rules shouldn't
    be silently failing in production either).
"""

from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("pandas", reason="pandas not installed")
pytest.importorskip("ortools", reason="ortools not installed")

from src.menu_rules import MenuRuleLoader
from src.preprocessor import ExcelReader, DataCleanser
from src.preprocessor.pool_builder import PoolBuilder
from src.solver.menu_solver import MenuSolver, SolverConfig


@pytest.fixture(scope="module")
def cleaned_menu(ensure_sample_data_exists):
    raw = ExcelReader(str(ensure_sample_data_exists)).read()
    return DataCleanser(raw).clean()


@pytest.fixture(scope="module")
def pools(cleaned_menu):
    return PoolBuilder.build_pools(cleaned_menu)


@pytest.fixture(scope="module")
def production_rules():
    """Load the shipped Bangalore ruleset — the same the API serves for a
    Bangalore client."""
    rules = MenuRuleLoader().load_for_city('Bangalore')
    assert rules, "expected shipped rules to load cleanly"
    return rules


# Keep a generous time budget on CI — this test is not trying to exercise
# the solver's fast-path, just prove it produces a plan with the full rule
# set on real data.
_TIME_LIMIT_SEC = 240


_ACTIVE_SLOTS = [
    'welcome_drink', 'starter', 'soup', 'salad',
    'rice', 'dal', 'veg_gravy', 'veg_dry', 'bread',
    'curd_side', 'dessert',
]


@pytest.mark.slow
def test_full_week_solve_with_production_rules(
    cleaned_menu, pools, production_rules,
):
    """A 5-weekday plan with the shipped rule set must fill every slot
    on every day and not leave any rule on rule_failures."""
    # Monday 2026-03-23 → Friday 2026-03-27 (the weekday range the
    # theme_map covers). Keeping to weekdays avoids dragging in the
    # weekend placeholder themes.
    start = dt.date(2026, 3, 23)
    cfg = SolverConfig(
        days=5,
        start_date=start,
        time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS,
        slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )

    solver = MenuSolver(
        pools=pools, solver_config=cfg, menu_rules=production_rules,
    )
    plan, dates = solver.solve()

    assert len(dates) == 5, "solver must return one entry per requested day"
    for d in dates:
        day_map = plan[d]
        for slot in _ACTIVE_SLOTS:
            assert slot in day_map, f"day {d} missing slot {slot!r}"
            assert day_map[slot], f"day {d} has empty item for slot {slot!r}"

    # Any soft rule that failed mid-solve lands here. In production we
    # surface it to the admin via the response; in CI we fail the run so
    # a regression in a rule's rule_config doesn't creep in unnoticed.
    assert not solver.rule_failures, (
        "production rules should not record any rule_failures on the "
        f"bundled ontology; got: {solver.rule_failures}"
    )


@pytest.mark.slow
def test_full_week_has_no_item_repeats_within_day(
    cleaned_menu, pools, production_rules,
):
    """Basic quality gate: the same item must not appear twice in one
    day's plan. The unique_items rule in the production config enforces
    this across the horizon, but this assertion guards the narrower
    per-day invariant explicitly."""
    cfg = SolverConfig(
        days=5,
        start_date=dt.date(2026, 3, 23),
        time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS,
        slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )

    solver = MenuSolver(
        pools=pools, solver_config=cfg, menu_rules=production_rules,
    )
    plan, dates = solver.solve()

    for d in dates:
        items = [plan[d][slot] for slot in _ACTIVE_SLOTS]
        # Strip color suffix — '(Y)' etc. — before dedupe so
        # 'jeera_rice(Y)' and 'jeera_rice(W)' still count as one item.
        from src.solver._helpers import strip_color_suffix
        bases = [strip_color_suffix(x) for x in items]
        assert len(set(bases)) == len(bases), (
            f"day {d} has a duplicate item across slots: {items}"
        )


@pytest.mark.slow
def test_combination_category_splits_week(cleaned_menu, pools, production_rules):
    """A dal/rasam combination slot must resolve to 3 dal + 2 rasam over a
    5-day week (real solve, production rules)."""
    from collections import Counter
    slots = ['dal_rasam', 'rice', 'veg_gravy', 'veg_dry', 'starter', 'dessert']
    cfg = SolverConfig(
        days=5,
        start_date=dt.date(2026, 3, 23),
        time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=slots,
        slot_counts={s: 1 for s in slots},
        const_slots=[],
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()

    course_by_item = dict(zip(cleaned_menu['item'], cleaned_menu['course_type']))
    from src.solver._helpers import strip_color_suffix
    variants = [course_by_item.get(strip_color_suffix(plan[d]['dal_rasam']))
                for d in dates]
    counts = Counter(variants)
    assert counts.get('dal') == 3 and counts.get('rasam') == 2, counts


@pytest.mark.slow
def test_dal_sambar_combo_splits_week(cleaned_menu, pools, production_rules):
    """A dal/sambar combination slot resolves to 3 dal + 2 sambar over a
    5-day week (dal is the majority variant)."""
    from collections import Counter
    slots = ['dal_sambar', 'rice', 'veg_gravy', 'veg_dry', 'starter', 'dessert']
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=slots, slot_counts={s: 1 for s in slots}, const_slots=[],
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()
    course_by_item = dict(zip(cleaned_menu['item'], cleaned_menu['course_type']))
    from src.solver._helpers import strip_color_suffix
    variants = [course_by_item.get(strip_color_suffix(plan[d]['dal_sambar']))
                for d in dates]
    counts = Counter(variants)
    assert counts.get('dal') == 3 and counts.get('sambar') == 2, counts


@pytest.mark.slow
def test_common_only_pool_feasible_and_gets_buttermilk(
    cleaned_menu, production_rules,
):
    """A common-only eligible pool (unconfigured client under the always-on
    pool model) must be FEASIBLE and — because buttermilk items are now part
    of the common pool — still get its 2 buttermilk days."""
    from src.preprocessor.pool_builder import PoolBuilder
    from src.preprocessor.client_pool_filter import get_active_pools, filter_eligible
    common = filter_eligible(cleaned_menu, get_active_pools([]))
    common_pools = PoolBuilder.build_pools(common)
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=common_pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()
    assert len(dates) == 5
    for d in dates:
        for slot in _ACTIVE_SLOTS:
            assert plan[d].get(slot), f"day {d} missing slot {slot!r}"
    assert not solver.rule_failures, solver.rule_failures
    from src.solver._helpers import strip_color_suffix
    bm = dict(zip(cleaned_menu['item'], cleaned_menu['is_buttermilk']))
    n_bm = sum(int(bm.get(strip_color_suffix(plan[d]['welcome_drink']), 0)) for d in dates)
    assert n_bm == 2, f"common-only should still get 2 buttermilk, got {n_bm}"


@pytest.mark.slow
def test_buttermilk_rule_degrades_when_pool_has_none(
    cleaned_menu, production_rules,
):
    """Belt-and-suspenders: if the active pool somehow contains no buttermilk
    items, the buttermilk rule must relax to 0 rather than force an
    INFEASIBLE `sum == 2`."""
    from src.preprocessor.pool_builder import PoolBuilder
    no_bm = cleaned_menu[cleaned_menu['is_buttermilk'] != 1].copy()
    pools = PoolBuilder.build_pools(no_bm)
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()
    assert len(dates) == 5  # feasible despite zero buttermilk candidates


@pytest.mark.slow
def test_selector_frequency_batch(cleaned_menu, pools, production_rules):
    """The Phase-1 selector_frequency rules hold on a real solve:
    liquid desserts = exactly 2 non-consecutive, and the weekly max caps
    (mixed-veg-gravy, black dal, pappu dal) are not exceeded."""
    import pandas as pd
    from src.solver._helpers import strip_color_suffix
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()

    def flag_map(col):
        return dict(zip(cleaned_menu['item'],
                        pd.to_numeric(cleaned_menu[col], errors='coerce').fillna(0).astype(int)))

    ld = flag_map('is_liquid_dessert')
    liquid_days = [i for i, d in enumerate(dates)
                   if ld.get(strip_color_suffix(plan[d]['dessert']), 0) == 1]
    assert len(liquid_days) == 2, f"expected 2 liquid desserts, got {liquid_days}"
    assert all(b - a > 1 for a, b in zip(liquid_days, liquid_days[1:])), liquid_days

    # Batch-1/2 + batch-3 weekly max caps (scoped to a base slot).
    for col, slot in [('is_mixedveg_gravy', 'veg_gravy'),
                      ('is_black_dal', 'dal'), ('is_pappu_dal', 'dal'),
                      ('is_custard_or_icecream', 'dessert'),
                      ('is_lassi', 'welcome_drink'),
                      ('is_soda_drink', 'welcome_drink'),
                      ('is_oil_based_bread', 'bread'),
                      ('is_leafy_based_dish', 'veg_dry'),
                      ('is_black_chana_gravy', 'veg_gravy'),
                      ('is_kabuli_chana_gravy', 'veg_gravy'),
                      ('is_rajma_gravy', 'veg_gravy')]:
        fm = flag_map(col)
        c = sum(fm.get(strip_color_suffix(plan[d][slot]), 0) for d in dates if slot in plan[d])
        assert c <= 1, f"{col} appeared {c} times (max 1)"

    # Sugar-syrup desserts (batch-3, non_consecutive-only rule) must not land
    # on adjacent days.
    ss = flag_map('is_sugar_syrup_heavy_dessert')
    ss_days = [i for i, d in enumerate(dates)
               if ss.get(strip_color_suffix(plan[d]['dessert']), 0) == 1]
    assert all(b - a > 1 for a, b in zip(ss_days, ss_days[1:])), (
        f"sugar-syrup desserts on consecutive days: {ss_days}"
    )


@pytest.mark.slow
def test_dal_colour_non_consecutive_and_sambar_key_ingredient(
    cleaned_menu, pools, production_rules,
):
    """Rulebook 79 + 82 (attribute_grouping): no two consecutive dal-service
    days share a dal colour, and no sambar key ingredient repeats in the week.
    Uses a dal+sambar slot layout so both rules bind."""
    from src.solver._helpers import strip_color_suffix
    slots = ['welcome_drink', 'rice', 'dal', 'sambar', 'veg_gravy', 'veg_dry',
             'bread', 'starter', 'dessert']
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=slots, slot_counts={s: 1 for s in slots},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()
    assert len(dates) == 5

    color_by_item = dict(zip(cleaned_menu['item'], cleaned_menu['item_color']))
    key_by_item = dict(zip(cleaned_menu['item'], cleaned_menu['key_ingredient']))

    dal_colours = [color_by_item.get(strip_color_suffix(plan[d]['dal'])) for d in dates]
    for a, b in zip(dal_colours, dal_colours[1:]):
        assert not (a and a == b), f"consecutive dal colour repeat: {dal_colours}"

    sambar_keys = [key_by_item.get(strip_color_suffix(plan[d]['sambar'])) for d in dates]
    present = [k for k in sambar_keys if k]
    assert len(present) == len(set(present)), (
        f"sambar key ingredient repeated in the week: {sambar_keys}"
    )
    assert not solver.rule_failures, solver.rule_failures


@pytest.mark.slow
def test_daily_colour_semantics(cleaned_menu, pools, production_rules):
    """Rulebook 88-91 on a real solve: across the colour-counted slots each
    day has >=4 distinct colours, every colour appears at most 3 times, and at
    most one colour reaches 3 (all others <=2)."""
    from collections import Counter
    from src.solver._helpers import strip_color_suffix
    from src.preprocessor.column_mapper import _norm_color
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()

    colour_of = {strip_color_suffix(i): _norm_color(c)
                 for i, c in zip(cleaned_menu['item'], cleaned_menu['item_color'])}
    counted = [s for s in cfg.color_slots if s in _ACTIVE_SLOTS]
    assert counted, "expected some colour-counted slots active"

    for d in dates:
        cols = [colour_of.get(strip_color_suffix(plan[d][s])) for s in counted if s in plan[d]]
        cols = [c for c in cols if c and c != 'unknown']
        counts = Counter(cols)
        assert len(counts) >= 4, f"{d}: only {len(counts)} distinct colours ({counts})"
        assert max(counts.values()) <= 3, f"{d}: a colour exceeds 3 ({counts})"
        at_three = [c for c, n in counts.items() if n >= 3]
        assert len(at_three) <= 1, f"{d}: more than one colour reaches 3 ({counts})"
    assert not solver.rule_failures, solver.rule_failures


@pytest.mark.slow
def test_ranked_alternates_are_distinct_and_valid(cleaned_menu, pools, production_rules):
    """n_alternates>0 returns several full valid menus ranked best-first; each
    fills every slot, they differ from one another, and none records a rule
    failure (they are near-optimal, not random)."""
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plans, dates = solver.solve(n_alternates=2)

    assert isinstance(plans, list) and len(plans) >= 2, "expected >=2 ranked menus"
    for plan in plans:
        assert len(plan) == 5
        for d in dates:
            for slot in _ACTIVE_SLOTS:
                assert plan[d].get(slot), f"menu missing {slot} on {d}"
    # Every returned menu is distinct from the others.
    sigs = [tuple(sorted((str(d), s, plan[d][s]) for d in dates for s in plan[d]))
            for plan in plans]
    assert len(set(sigs)) == len(sigs), "ranked alternates must be distinct menus"
    assert not solver.rule_failures, solver.rule_failures


@pytest.mark.slow
def test_premium_exactly_one_per_slot(cleaned_menu, pools, production_rules):
    """Rulebook 43-44: each week has exactly one Premium Veg Gravy and exactly
    one Premium Veg Dry (replacing the retired broad premium cap)."""
    import pandas as pd
    from src.solver._helpers import strip_color_suffix
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()

    def flag_map(col):
        return dict(zip(cleaned_menu['item'],
                        pd.to_numeric(cleaned_menu[col], errors='coerce').fillna(0).astype(int)))

    for col, slot in [('is_premium_gravy', 'veg_gravy'),
                      ('is_premium_veg_dry', 'veg_dry')]:
        fm = flag_map(col)
        c = sum(fm.get(strip_color_suffix(plan[d][slot]), 0) for d in dates if slot in plan[d])
        assert c == 1, f"{col} appeared {c} times in {slot} (want exactly 1)"
    assert not solver.rule_failures, solver.rule_failures


@pytest.mark.slow
def test_deep_fried_nonveg_weekly_cap(cleaned_menu, pools, production_rules):
    """With the non-veg main slot active, the batch-3 deep-fried-nonveg weekly
    cap holds and the week still solves cleanly."""
    import pandas as pd
    from src.solver._helpers import strip_color_suffix
    slots = _ACTIVE_SLOTS + ['nonveg_main']
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=slots, slot_counts={s: 1 for s in slots},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()

    assert len(dates) == 5
    for d in dates:
        assert plan[d].get('nonveg_main'), f"day {d} missing nonveg_main"

    dfn = dict(zip(cleaned_menu['item'],
                   pd.to_numeric(cleaned_menu['is_deep_fried_nonveg_dry'],
                                 errors='coerce').fillna(0).astype(int)))
    c = sum(dfn.get(strip_color_suffix(plan[d]['nonveg_main']), 0) for d in dates)
    assert c <= 1, f"deep-fried non-veg appeared {c} times (max 1)"
    assert not solver.rule_failures, solver.rule_failures


@pytest.mark.slow
def test_two_nonveg_two_vegdry_daily_composition(
    cleaned_menu, pools, production_rules,
):
    """A 2-nonveg / 2-veg_dry counter solves feasibly and each day's nonveg
    pair is composed by the day's theme (rulebook: 2 nonveg mains):
      biryani day -> a nonveg biryani + a chicken gravy
      chinese day -> a chinese nonveg  + a north/south chicken gravy
      other days  -> a nonveg dry      + a north/south chicken gravy
    and the veg_dry pair is one north-Indian + one south-Indian on the mix day.
    """
    import pandas as pd
    from src.solver._helpers import strip_color_suffix
    slots = ['welcome_drink', 'rice', 'dal', 'veg_gravy', 'veg_dry', 'bread',
             'starter', 'dessert', 'nonveg_main']
    counts = {s: 1 for s in slots}
    counts['nonveg_main'] = 2
    counts['veg_dry'] = 2
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=slots, slot_counts=counts,
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()
    assert len(dates) == 5

    def flag_map(col):
        return dict(zip(cleaned_menu['item'],
                        pd.to_numeric(cleaned_menu[col], errors='coerce').fillna(0).astype(int)))

    cuisine = dict(zip(cleaned_menu['item'],
                       cleaned_menu['cuisine_family'].astype(str).str.lower()))
    is_dry = flag_map('is_nonveg_dry')
    is_biryani = flag_map('is_nonveg_biryani')
    is_north = flag_map('is_north_chicken_gravy')
    is_south = flag_map('is_south_chicken_gravy')

    # Default theme_map: Mon=mix, Tue=chinese, Wed=biryani, Thu=south, Fri=north.
    themes = ['mix', 'chinese', 'biryani', 'south', 'north']
    for di, d in enumerate(dates):
        nv = [strip_color_suffix(v) for k, v in plan[d].items()
              if k.startswith('nonveg_main')]
        assert len(nv) == 2, f"{d}: expected 2 nonveg mains, got {nv}"
        n_gravy = sum(1 for x in nv if is_north.get(x, 0) or is_south.get(x, 0))
        if themes[di] == 'biryani':
            assert any(is_biryani.get(x, 0) for x in nv), f"{d}: no biryani in {nv}"
            assert n_gravy >= 1, f"{d}: no chicken gravy beside biryani in {nv}"
        elif themes[di] == 'chinese':
            assert any(cuisine.get(x) == 'chinese' for x in nv), f"{d}: no chinese nonveg in {nv}"
            assert n_gravy >= 1, f"{d}: no gravy beside chinese nonveg in {nv}"
        else:  # chicken day
            assert any(is_dry.get(x, 0) for x in nv), f"{d}: no dry nonveg in {nv}"
            assert n_gravy >= 1, f"{d}: no north/south gravy in {nv}"

    # veg_dry pair on the mix day (Mon, no theme narrowing) = one north + one south.
    vd = [strip_color_suffix(v) for k, v in plan[dates[0]].items()
          if k.startswith('veg_dry')]
    assert len(vd) == 2, vd
    vd_cuisines = sorted(cuisine.get(x) for x in vd)
    assert 'north_indian' in vd_cuisines and 'south_indian' in vd_cuisines, vd_cuisines

    assert not solver.rule_failures, solver.rule_failures


@pytest.mark.slow
def test_buttermilk_exactly_twice_non_consecutive(
    cleaned_menu, pools, production_rules,
):
    """The welcome-drink slot is buttermilk on exactly 2 non-consecutive days
    of a 5-day week (solver picks which)."""
    cfg = SolverConfig(
        days=5, start_date=dt.date(2026, 3, 23), time_limit_sec=_TIME_LIMIT_SEC,
        active_base_slots=_ACTIVE_SLOTS, slot_counts={s: 1 for s in _ACTIVE_SLOTS},
    )
    solver = MenuSolver(pools=pools, solver_config=cfg, menu_rules=production_rules)
    plan, dates = solver.solve()

    from src.solver._helpers import strip_color_suffix
    bm = dict(zip(cleaned_menu['item'], cleaned_menu['is_buttermilk']))
    flags = [int(bm.get(strip_color_suffix(plan[d]['welcome_drink']), 0)) for d in dates]
    positions = [i for i, f in enumerate(flags) if f]
    assert len(positions) == 2, f"expected 2 buttermilk days, got {positions}"
    assert all(b - a > 1 for a, b in zip(positions, positions[1:])), (
        f"buttermilk days must not be consecutive: {positions}"
    )
