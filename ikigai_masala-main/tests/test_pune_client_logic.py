"""Amadeus Pune's client logic, against the client's own sample week.

Source: `docs/pune_client_logic.md` (transcribed from the client's sample menu).
Nine stated rules and a seven-day grid; these tests assert the generated menu has
the same *shape* as that grid — which slots run on which weekdays, and the
weekly rhythm of paneer/soya/chapati/buttermilk. Dish-for-dish equality is not
the goal (the sample is one week of many), so the assertions are on structure.

Also pins the three engine fixes the client needed, each of which was a silent
failure before:

* ``fixed_daily_item`` on a slot that also has a ``slot_day_restriction``
* the per-day colour-variety clamp when a day has fewer colour cells than the
  counter's config implies
* a ``constant_items`` pin naming a dish the ontology carries under a different
  course type
"""

import datetime as dt

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'      # Monday, ISO week 32
TIME_LIMIT = 60

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
WEEKDAYS = {MON, TUE, WED, THU, FRI}


@pytest.fixture(scope='module')
def amadeus_pune_row():
    from tests.client_fixtures import CLIENTS
    return next(dict(c) for c in CLIENTS if c['name'] == 'Amadeus Pune')


@pytest.fixture(scope='module')
def plan(amadeus_pune_row):
    """One seven-day solve, shared by every assertion below."""
    import src.db as db_mod
    import api.app as api_app
    from api.rate_limit import reset_for_tests

    fake = FakeSupabase(seed={
        'clients': [amadeus_pune_row], 'app_settings': [],
        'menu_history': [], 'week_signatures': [],
    })
    old_sb = getattr(db_mod, '_sb_client', None)
    db_mod._sb_client = fake
    api_app._client_loader = None
    for attr in ('_menu_data_by_path', '_nonveg_items_by_path',
                 '_menu_rules_by_city', '_filtered_cache'):
        setattr(api_app, attr, {})
    api_app.app.config['TESTING'] = True
    try:
        reset_for_tests()
        resp = api_app.app.test_client().post('/api/v1/plan', json={
            'client_name': 'Amadeus Pune', 'start_date': MONDAY,
            'num_days': 7, 'time_limit_seconds': TIME_LIMIT,
        })
        body = resp.get_json() or {}
        assert resp.status_code == 200, body.get('error') or body.get('message')
        yield body
    finally:
        db_mod._sb_client = old_sb
        api_app._client_loader = None


@pytest.fixture(scope='module')
def pune_df():
    from api.config import city_excel_path
    from src.preprocessor.data_cleanser import DataCleanser
    from src.preprocessor.excel_reader import ExcelReader
    return DataCleanser(ExcelReader(city_excel_path('Pune')).read()).clean()


def _by_weekday(plan, slot):
    """``{weekday_index: item_base}`` for one slot; absent days are omitted."""
    out = {}
    for key, day in plan['solution'].items():
        entry = day['items'].get(slot)
        if entry:
            out[dt.date.fromisoformat(key).weekday()] = entry['item_base']
    return out


def _attr(df, item, col):
    row = df[df['item'] == item]
    return None if row.empty else row.iloc[0][col]


def _is(df, item, flag):
    v = _attr(df, item, flag)
    return bool(pd.to_numeric(pd.Series([v]), errors='coerce').fillna(0).iloc[0])


class TestServiceDaysMatchTheSample:
    """'sat and Sunday also working', 'sat no veg dry it should be blank', and
    'in sun we server only flvour rice(any veg biryani), papad, welcom drinl and
    sweet that's all'."""

    def test_seven_service_days(self, plan):
        assert len(plan['solution']) == 7

    @pytest.mark.parametrize('slot,expected', [
        ('salad', {MON, TUE, WED, THU, FRI, SAT, SUN}),   # Sunday's is the raita
        ('veg_gravy', {MON, TUE, WED, THU, FRI, SAT}),
        ('veg_dry', WEEKDAYS),                            # blank Sat AND Sun
        ('dal', {MON, TUE, WED, THU, FRI, SAT}),
        ('bread', {MON, TUE, WED, THU, FRI, SAT}),
        ('white_rice', {MON, TUE, WED, THU, FRI, SAT}),
        ('rice', {TUE, SUN}),                             # 'flavour rice on Tue and sun'
        ('papad', {MON, TUE, WED, THU, FRI, SAT, SUN}),
        ('welcome_drink', {MON, TUE, WED, THU, FRI, SAT, SUN}),
        ('dessert', {MON, TUE, WED, THU, FRI, SAT, SUN}),
    ])
    def test_slot_runs_on_exactly_these_weekdays(self, plan, slot, expected):
        assert set(_by_weekday(plan, slot)) == expected

    def test_every_dish_comes_from_the_pune_list(self, plan, pune_df):
        """The real client, not just the reference counter next door: 123 of
        Pune's 274 items also exist in Bangalore, so a spot check would not catch
        a plan built off the wrong ontology."""
        pune_items = set(pune_df['item'])
        stamped = {'steamed rice', 'Papad', 'Raita'}
        for key, day in plan['solution'].items():
            for slot, entry in day['items'].items():
                name = entry['item_base']
                if name in stamped:
                    continue
                assert name in pune_items, f"{key}/{slot}={name} is not a Pune item"

    def test_sunday_serves_only_the_five_stated_rows(self, plan):
        sunday = next(
            day for key, day in plan['solution'].items()
            if dt.date.fromisoformat(key).weekday() == SUN
        )
        assert set(sunday['items']) == {
            'rice', 'salad', 'papad', 'welcome_drink', 'dessert',
        }


class TestWeeklyRhythm:
    def test_chapati_every_service_day(self, plan, pune_df):
        """'chapati daily in indain bread'.

        Meaningful only because phulka is an eligible alternative — the assertion
        is that the rule picks chapati, not that chapati is the only option.
        """
        assert 'phulka' in set(pune_df[pune_df.course_type == 'bread']['item'])
        breads = _by_weekday(plan, 'bread')
        assert set(breads.values()) == {'chapati'}, breads

    def test_buttermilk_every_day(self, plan):
        """'welcome drink will have butter milk daily'."""
        drinks = _by_weekday(plan, 'welcome_drink')
        assert set(drinks.values()) == {'buttermilk'}, drinks

    def test_white_rice_is_the_daily_steamed_rice(self, plan):
        """'white rice daily' — except Sunday, which is biryani-only."""
        rices = _by_weekday(plan, 'white_rice')
        assert set(rices.values()) == {'steamed rice'}, rices

    def test_exactly_one_paneer_dish_a_week(self, plan, pune_df):
        """'weekly 1 panner' — counted across every slot, not just the gravy."""
        hits = [
            (key, e['item_base'])
            for key, day in plan['solution'].items()
            for e in day['items'].values()
            if str(_attr(pune_df, e['item_base'], 'key_ingredient')).lower() == 'paneer'
        ]
        assert len(hits) == 1, hits

    def test_exactly_one_soya_dish_a_week(self, plan, pune_df):
        """'weekly 1 soya'."""
        hits = [
            (key, e['item_base'])
            for key, day in plan['solution'].items()
            for e in day['items'].values()
            if str(_attr(pune_df, e['item_base'], 'key_ingredient')).lower() == 'soy'
        ]
        assert len(hits) == 1, hits

    def test_sunday_rice_is_a_veg_biryani(self, plan, pune_df):
        """'in sun we server only flvour rice(any veg biryani)' — any, so the
        solver picks between veg_biryani and handi_biryani."""
        sunday_rice = _by_weekday(plan, 'rice')[SUN]
        assert _is(pune_df, sunday_rice, 'is_mixedveg_biryani'), sunday_rice

    def test_tuesday_rice_is_a_flavoured_rice_not_the_biryani(self, plan, pune_df):
        """The city ruleset caps mixed-veg pulao/biryani at one a week (R19), and
        Sunday spends it."""
        tuesday_rice = _by_weekday(plan, 'rice')[TUE]
        assert not _is(pune_df, tuesday_rice, 'is_mixedveg_biryani')
        assert not _is(pune_df, tuesday_rice, 'is_mixedveg_pulao')

    def test_sunday_salad_row_is_the_raita(self, plan):
        """The sample's Sunday salad column is RAITA. `raita` is a real Pune dish
        filed under `curd_side`, so it is not a `salad` candidate and the pin is
        stamped as text rather than solved."""
        assert _by_weekday(plan, 'salad')[SUN] == 'Raita'


class TestNoDiagnosticNoise:
    def test_diagnose_is_clean(self, amadeus_pune_row, monkeypatch):
        """No errors AND no warnings.

        The warnings this used to emit were both wrong: bread and welcome_drink
        are declared staples (chapati daily, buttermilk daily), so "items will
        repeat" is the configured intent, not a shortfall. Two bogus warnings on
        every plan is how a real one gets missed.
        """
        import src.db as db_mod
        import api.app as api_app
        from api.rate_limit import reset_for_tests

        fake = FakeSupabase(seed={
            'clients': [dict(amadeus_pune_row)], 'app_settings': [],
            'menu_history': [], 'week_signatures': [],
        })
        monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
        monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
        for attr in ('_menu_data_by_path', '_nonveg_items_by_path',
                     '_menu_rules_by_city', '_filtered_cache'):
            monkeypatch.setattr(api_app, attr, {}, raising=False)
        reset_for_tests()
        resp = api_app.app.test_client().post('/api/v1/diagnose', json={
            'client_name': 'Amadeus Pune', 'start_date': MONDAY, 'num_days': 7,
        })
        body = resp.get_json()
        assert resp.status_code == 200
        noisy = [
            d for d in body['rule_diagnostics']
            if d['severity'] in ('error', 'warning')
        ]
        assert not noisy, noisy


class TestEngineFixesThisClientNeeded:
    def test_fixed_daily_item_counts_the_slot_s_own_days(self):
        """``fixed_daily_item`` used to require the dish on every day of the
        HORIZON. Bread runs Mon-Sat, so over a 7-day horizon chapati appeared on
        6 of 7 days, was judged ineligible and pinned to zero — and with phulka
        pinned the same way the six bread cells had no candidate at all.

        Pinning chapati on the first day makes the difference observable: it is
        INFEASIBLE under the old rule and lands on all six days under the fixed
        one.
        """
        from ortools.sat.python import cp_model
        from src.menu_rules.fixed_daily_item_rule import FixedDailyItemRule

        class Cell:
            def __init__(self, d_idx, base_slot, rows, model):
                self.d_idx = d_idx
                self.base_slot = base_slot
                self.cand_rows = rows
                self.x_vars = [
                    model.NewBoolVar(f'{base_slot}_{d_idx}_{i}')
                    for i, _r in enumerate(rows)
                ]

        model = cp_model.CpModel()
        rows = [{'item': 'chapati'}, {'item': 'phulka'}]
        # Six bread cells over a seven-day horizon (Sunday has none).
        cells = [Cell(di, 'bread', rows, model) for di in range(6)]
        for cell in cells:
            model.Add(sum(cell.x_vars) == 1)
        model.Add(cells[0].x_vars[0] == 1)      # day 0 serves chapati
        rule = FixedDailyItemRule({
            'name': 'chapati_daily', 'type': 'fixed_daily_item',
            'base_slot': 'bread', 'selector': {'item': 'chapati'},
        })
        rule.apply(model, {}, None, {
            'cells': cells, 'dates': [object()] * 7,
        })
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        for cell in cells:
            picked = [
                r['item'] for r, v in zip(cell.cand_rows, cell.x_vars)
                if solver.Value(v)
            ]
            assert picked == ['chapati'], picked

    def test_composition_treats_a_declared_staple_as_unlimited(self):
        """"Chapati daily" is one distinct item over six days, which reads as a
        horizon shortfall — ``_horizon_limited_components`` would swap the daily
        mandate for a floor of one, turning "chapati daily" into "chapati once".
        A staple is unlimited by definition, and the declaration that says so now
        reaches this check too (it only consulted the ontology-wide flags).
        """
        from src.menu_rules.repeatable_items_rule import RepeatableItemsRule
        from src.menu_rules.slot_composition_rule import SlotCompositionRule
        from src.solver.menu_solver import SolverConfig

        class Cell:
            def __init__(self, d_idx):
                self.d_idx = d_idx
                self.base_slot = 'bread'
                self.cand_rows = [
                    {'item': 'chapati', 'is_plain_phulka_chapathi': 1},
                    {'item': 'phulka', 'is_plain_phulka_chapathi': 1},
                ]
                self.x_vars = [None, None]

        rule = SlotCompositionRule({
            'name': 'chapati_daily', 'type': 'slot_composition',
            'base_slot': 'bread', 'min_slot_count': 1,
            'components': [{'selector': {'item': 'chapati'}, 'count': 1}],
        })
        cells = [Cell(di) for di in range(6)]
        dates = [dt.date(2026, 8, 3) + dt.timedelta(days=i) for i in range(6)]
        base_ctx = {
            'cfg': SolverConfig(days=6, start_date=dates[0],
                                slot_counts={'bread': 1}),
            'cells': cells, 'dates': dates,
        }
        day_types = ['north'] * 6

        limited = rule._horizon_limited_components(
            cells, dates, day_types, base_ctx)
        assert limited, "one distinct item over six days is a horizon shortfall"

        declared = RepeatableItemsRule({
            'name': 'staple', 'type': 'repeatable_items', 'base_slot': 'bread',
            'selector': {'flag': 'is_plain_phulka_chapathi'},
        }).repeatable_item_flags()
        limited = rule._horizon_limited_components(
            cells, dates, day_types,
            {**base_ctx, 'extra_repeatable': {k: [v] for k, v in declared.items()}},
        )
        assert limited == {}, "a declared staple is never horizon-limited"

    def test_colour_minimum_clamps_to_the_day_s_own_cells(self):
        """A day with two colour cells cannot show three distinct colours. The
        clamp was computed from the counter's CONFIG, which counts slots that
        skip_cells removed — Amadeus Pune's Sunday has five colour slots
        configured and two served.
        """
        import datetime as date_mod
        from src.solver.menu_solver import MenuSolver, SolverConfig

        pool = pd.DataFrame([
            {'item': f'dish_{c}', 'course_type': 'dessert', 'item_color': c,
             'cuisine_family': 'north_indian', 'sub_category': 's',
             'key_ingredient': 'k'}
            for c in ('red', 'green', 'white', 'yellow', 'brown')
        ])
        rice = pool.assign(course_type='rice',
                           item=[f'rice_{c}' for c in
                                 ('red', 'green', 'white', 'yellow', 'brown')])
        cfg = SolverConfig(
            days=1, start_date=date_mod.date(2026, 8, 9),
            explicit_dates=[date_mod.date(2026, 8, 9)],
            active_base_slots=['rice', 'veg_gravy', 'veg_dry', 'dal', 'dessert'],
            slot_counts={s: 1 for s in
                         ('rice', 'veg_gravy', 'veg_dry', 'dal', 'dessert')},
            const_slots=[],
            min_distinct_colors_per_day=3,
            max_colors_at_reach=0,
            time_limit_sec=20,
        )
        pools = {
            'rice': rice, 'dessert': pool,
            'veg_gravy': pool.assign(course_type='veg_gravy'),
            'veg_dry': pool.assign(course_type='veg_dry'),
            'dal': pool.assign(course_type='dal'),
        }
        d = date_mod.date(2026, 8, 9)
        solver = MenuSolver(
            pools=pools, solver_config=cfg, menu_rules=[],
            # Three of the five colour slots are off today: two cells remain,
            # so three distinct colours is arithmetically impossible.
            skip_cells={(d, 'veg_gravy'), (d, 'veg_dry'), (d, 'dal')},
        )
        week_plan, dates = solver.solve()
        assert dates == [d]
        assert set(week_plan[d]) == {'rice', 'dessert'}

    def test_pin_outside_the_slot_pool_is_stamped_not_dropped(self):
        """A pin naming a dish the ontology carries under a DIFFERENT course type
        has no candidate in this slot. It used to be routed to `forced_items`
        (because the ontology knows the name), fail to match, get solved
        normally — and then be skipped by the stamping pass for being in
        `forced_items`. The pin vanished with only an INFO line to show for it.
        """
        import api.app as api_app
        from src.client.client_config import ClientConfig

        pools = {
            'salad': pd.DataFrame([{'item': 'green_salad'}]),
            'curd_side': pd.DataFrame([{'item': 'raita'}]),
        }
        assert api_app._slot_item_names(pools, 'salad') == frozenset({'green_salad'})
        assert 'raita' not in api_app._slot_item_names(pools, 'salad')

        cfg = ClientConfig(
            name='t', active_slots=['salad'], slot_counts={'salad': 1},
            theme_map={},
        )
        resolved, whole = api_app._resolve_constant_items(
            't', {'salad': {'sunday': 'Raita'}}, cfg,
        )
        assert resolved == {'salad': {'sunday': 'Raita'}}
        assert whole == set()   # a weekday map never replaces the whole slot

    def test_underscore_keys_in_constant_items_are_documentation(self):
        """`_comment` inside a constant_items block used to log 'not a known
        slot' on every plan."""
        import api.app as api_app
        from src.client.client_config import ClientConfig

        cfg = ClientConfig(
            name='t', active_slots=['bread'], slot_counts={'bread': 1},
            theme_map={},
        )
        resolved, _whole = api_app._resolve_constant_items(
            't', {'_comment': 'why', 'bread': 'chapati'}, cfg,
        )
        assert resolved == {'bread': 'chapati'}

    def test_unique_items_diagnose_is_quiet_about_declared_staples(self):
        """A slot whose staples a peer rule declared can never be starved —
        apply() skips it — so warning about it was always wrong."""
        from src.menu_rules.base_menu_rule import DiagnoseContext
        from src.menu_rules.repeatable_items_rule import RepeatableItemsRule
        from src.menu_rules.unique_items_menu_rule import UniqueItemsMenuRule
        from src.solver.menu_solver import SolverConfig

        bread = pd.DataFrame([
            {'item': 'chapati', 'is_plain_phulka_chapathi': 1},
            {'item': 'phulka', 'is_plain_phulka_chapathi': 1},
        ])
        dates = [dt.date(2026, 8, 3) + dt.timedelta(days=i) for i in range(6)]
        cfg = SolverConfig(days=6, start_date=dates[0])
        ctx = DiagnoseContext(
            cfg=cfg, pools={'bread': bread}, dates=dates,
            day_types={d: 'north' for d in dates},
            active_base_slots=['bread'],
            client_cfg=ClientCfgStub(),
            df=bread, skip_cells=set(),
            banned_by_date={}, ricebread_ban_day={},
        )
        rule = UniqueItemsMenuRule(
            {'name': 'u', 'type': 'unique_items', 'scope': 'session'})

        rule._peer_rules = []
        assert rule.diagnose(ctx), "2 items for 6 days must warn without the rule"

        rule._peer_rules = [RepeatableItemsRule({
            'name': 'staple', 'type': 'repeatable_items', 'base_slot': 'bread',
            'selector': {'flag': 'is_plain_phulka_chapathi'},
        })]
        assert rule.diagnose(ctx) == []


class ClientCfgStub:
    slot_counts = {'bread': 1}
    active_slots = ['bread']
    theme_map: dict = {}
    name = 'stub'
