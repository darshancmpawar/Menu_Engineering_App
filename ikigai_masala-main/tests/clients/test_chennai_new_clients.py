"""TCL, Gartner, World Bank and ICON Chn against real solves.

Their logic came from `data/raw/source_workbooks/chennai_client_structure.xlsx`
— stated rules on `Sheet1`, a sample week per client on its own sheet. RNTBCI is
in the same workbook with an EMPTY sheet and no stated rules, so it is
deliberately absent here.

The counters mirror the live `clients` rows, with two exceptions that the config
files' `_needs_db_change` notes also record and that are made here so the rules
are actually exercised: TCL serves the weekend and World Bank's non-veg station
runs four dishes. Where a rule is inert until the DB changes, the test says so
rather than asserting a behaviour the shipped config does not produce.
"""

from __future__ import annotations

import pytest

from tests.fake_supabase import FakeSupabase

pytestmark = pytest.mark.slow

MONDAY = '2026-08-10'
TIME_LIMIT = 60


def _counter(name, categories, slot_counts, theme_map):
    return {'name': name, 'theme_map': theme_map, 'categories': categories,
            'slot_counts': slot_counts}


WEEKDAYS = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6}

CLIENTS = {
    # serve_weekends is TRUE here and false live — the client works Saturday and
    # Sunday and the whole reduced-weekend rule set is about that.
    'TCL': {
        'name': 'TCL', 'version': 1, 'city': 'Chennai', 'serve_weekends': True,
        'item_cooldown_days': 20, 'source_pools': [],
        'counters': [_counter(
            'Counter 1',
            ['welcome_drink', 'salad', 'bread', 'rice', 'veg_dry', 'veg_gravy',
             'dal', 'sambar', 'rasam', 'dessert', 'nonveg_main', 'curd_rice',
             'white_rice', 'papad'],
            {'dal': 1, 'rice': 2, 'bread': 1, 'rasam': 1, 'salad': 1,
             'sambar': 1, 'dessert': 1, 'veg_dry': 1, 'curd_rice': 1,
             'veg_gravy': 1, 'nonveg_main': 1, 'welcome_drink': 1},
            {'monday': 'mix', 'tuesday': 'south', 'wednesday': 'mix',
             'thursday': 'south', 'friday': 'mix'})],
    },
    'Gartner': {
        'name': 'Gartner', 'version': 1, 'city': 'Chennai',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'counters': [_counter(
            'Counter 1',
            ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dessert',
             'nonveg_main', 'white_rice'],
            {'rice': 1, 'bread': 1, 'salad': 1, 'dessert': 1, 'veg_dry': 1,
             'veg_gravy': 1, 'nonveg_main': 1},
            {'monday': 'biryani', 'tuesday': 'mix', 'wednesday': 'mix',
             'thursday': 'south', 'friday': 'chinese'})],
    },
    # nonveg_main is 4 here and 2 live: the client lists four non-veg items
    # daily and the sample prints all four.
    'World Bank': {
        'name': 'World Bank', 'version': 1, 'city': 'Chennai',
        'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
        'shared_categories': ['veg_dry', 'veg_gravy'],
        'counters': [
            _counter(
                'Full Lunch Menu',
                ['bread', 'veg_dry', 'veg_gravy', 'nonveg_main', 'rice',
                 'white_rice', 'dal', 'sambar', 'rasam', 'dessert',
                 'welcome_drink'],
                {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'sambar': 1,
                 'dessert': 1, 'veg_dry': 1, 'veg_gravy': 1, 'nonveg_main': 4,
                 'welcome_drink': 1},
                {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'mix',
                 'thursday': 'south', 'friday': 'mix'}),
            _counter(
                'Roti and Rice Combos',
                ['bread', 'rice', 'veg_dry', 'veg_gravy', 'nonveg_main'],
                {'rice': 1, 'bread': 2, 'veg_dry': 1, 'veg_gravy': 1,
                 'nonveg_main': 1},
                {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'north',
                 'thursday': 'south', 'friday': 'north'}),
        ],
    },
    'ICON Chn': {
        'name': 'ICON Chn', 'version': 1, 'city': 'Chennai',
        'serve_weekends': False, 'item_cooldown_days': 20,
        'source_pools': ['accenture', 'icon', 'ltm', 'rntbci',
                         'tata communications', 'toast tab', 'wells fargo',
                         'world bank'],
        'shared_categories': ['white_rice', 'dessert', 'rasam', 'sambar',
                              'bread', 'welcome_drink', 'dal', 'veg_dry',
                              'veg_gravy'],
        'counters': [
            _counter(
                'Premium Lunch',
                ['welcome_drink', 'bread', 'white_rice', 'veg_dry',
                 'veg_gravy', 'starter', 'dal', 'sambar', 'rasam', 'dessert',
                 'nonveg_main'],
                {'dal': 1, 'bread': 1, 'rasam': 1, 'sambar': 1, 'dessert': 1,
                 'starter': 1, 'veg_dry': 1, 'veg_gravy': 1, 'nonveg_main': 3,
                 'welcome_drink': 1},
                {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'south',
                 'thursday': 'south', 'friday': 'north'}),
            _counter(
                'Economy Lunch',
                ['welcome_drink', 'white_rice', 'veg_dry', 'veg_gravy', 'dal',
                 'sambar', 'rasam', 'dessert', 'nonveg_main'],
                {'dal': 1, 'rasam': 1, 'sambar': 1, 'dessert': 1,
                 'veg_dry': 1, 'veg_gravy': 1, 'nonveg_main': 1,
                 'welcome_drink': 1},
                {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'south',
                 'thursday': 'south', 'friday': 'north'}),
            _counter(
                'Rice Combo',
                ['rice', 'veg_dry', 'veg_gravy', 'dessert', 'nonveg_main'],
                {'rice': 1, 'dessert': 1, 'veg_dry': 1, 'veg_gravy': 1,
                 'nonveg_main': 1},
                {d: 'south' for d in WEEKDAYS}),
            _counter(
                'Roti Combo',
                ['bread', 'veg_gravy', 'dessert', 'nonveg_main'],
                {'bread': 1, 'dessert': 1, 'veg_gravy': 1, 'nonveg_main': 1},
                {'monday': 'mix', 'tuesday': 'north', 'wednesday': 'north',
                 'thursday': 'north', 'friday': 'north'}),
        ],
    },
}


@pytest.fixture(scope='module')
def chn_df():
    import pandas as pd
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Chennai'))


@pytest.fixture(scope='module')
def solved():
    """Every counter of all four clients, solved once.

    Module-scoped on purpose: eight solves at 60s apiece is the bulk of this
    file's runtime, and the per-test `monkeypatch` fixture cannot be reached
    from a class-scoped one anyway (pytest refuses the scope mismatch). The DB
    swap is undone in the teardown rather than by monkeypatch.
    """
    import api.app as api_app
    import src.db as db_mod
    from api.rate_limit import reset_for_tests

    fake = FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS.values()],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    })
    previous = getattr(db_mod, '_sb_client', None)
    db_mod._sb_client = fake
    api_app._client_loader = None
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    out = {}
    try:
        for name, row in CLIENTS.items():
            days = 7 if row['serve_weekends'] else 5
            out[name] = []
            for idx in range(len(row['counters'])):
                reset_for_tests()
                resp = api_app.app.test_client().post('/api/v1/plan', json={
                    'client_name': name, 'start_date': MONDAY,
                    'num_days': days, 'time_limit_seconds': TIME_LIMIT,
                    'counter_index': idx})
                body = resp.get_json() or {}
                assert resp.status_code == 200, (
                    name, idx, body.get('error') or body.get('message'))
                out[name].append(_by_weekday(body['solution']))
        yield out
    finally:
        db_mod._sb_client = previous
        api_app._client_loader = None
        api_app.reset_caches()


def _by_weekday(solution):
    """{weekday index: {slot_id: item_base}} for a solved plan."""
    import datetime as dt
    out = {}
    for iso, day in solution.items():
        wd = dt.date.fromisoformat(iso).weekday()
        out[wd] = {slot: it.get('item_base')
                   for slot, it in (day.get('items') or {}).items()}
    return out


def _row(chn_df, item):
    hit = chn_df[chn_df['item'].astype(str).str.strip().str.lower() == item]
    assert len(hit) == 1, item
    return hit.iloc[0]


# --------------------------------------------------------------------------
# TCL — thirteen stated rules, seven-day service
# --------------------------------------------------------------------------
class TestTCL:
    @pytest.fixture(scope='class')
    def days(self, solved):
        return solved['TCL'][0]

    def test_it_plans_all_seven_days(self, days):
        assert sorted(days) == list(range(7))

    def test_the_dal_is_always_a_kootu(self, days, chn_df):
        for wd, day in days.items():
            if 'dal' not in day:
                continue
            assert _row(chn_df, day['dal'])['sub_category'] == 'kootu', wd

    def test_the_bread_is_always_a_chapati(self, days, chn_df):
        for wd, day in days.items():
            assert int(_row(chn_df, day['bread'])
                       ['is_plain_phulka_chapathi']) == 1, wd

    def test_one_rice_is_a_biryani_and_the_other_a_south_rice(self, days,
                                                              chn_df):
        south = {'south_one_pot_rice', 'south_rice_bath', 'south_veg_pulao'}
        for wd, day in days.items():
            rices = {v for k, v in day.items() if k.startswith('rice')}
            if len(rices) < 2:
                continue
            rows = [_row(chn_df, r) for r in rices]
            assert any(int(r['is_biryani_item']) == 1 for r in rows), wd
            assert any(str(r['sub_category']) in south for r in rows), wd

    def test_saturday_serves_one_rice_and_sunday_none(self, days):
        sat = {k for k in days[5] if k.startswith('rice')}
        assert len(sat) == 1, sat
        assert not {k for k in days[6] if k.startswith('rice')}

    def test_the_weekend_menus_are_the_reduced_ones(self, days):
        """Saturday: chapati, one south rice, curd rice, veg gravy, drink, veg
        dry, papad. Sunday: chapati, white rice, sambar, rasam, dal, veg gravy,
        drink, salad, papad."""
        for slot in ('dal', 'sambar', 'rasam', 'dessert', 'nonveg_main',
                     'salad'):
            assert slot not in days[5], f'{slot} should be off on Saturday'
        for slot in ('veg_dry', 'dessert', 'nonveg_main', 'curd_rice'):
            assert slot not in days[6], f'{slot} should be off on Sunday'
        assert 'curd_rice' in days[5]
        assert 'salad' in days[6] and 'dal' in days[6]

    def test_no_premium_veg_on_the_weekend(self, days, chn_df):
        """"no item like baby corn, panner and mushroom will given on sat and
        sun" — counted across every slot, because the point is the plate."""
        lookup = chn_df.set_index(
            chn_df['item'].astype(str).str.strip().str.lower())
        for wd in (5, 6):
            for slot, item in days[wd].items():
                key = str(item).strip().lower()
                if key not in lookup.index:
                    continue        # a CONST slot: steamed rice, papad, pickle
                row = lookup.loc[key]
                assert not any(w in key for w in
                               ('paneer', 'mushroom', 'baby_corn', 'babycorn')), \
                    (wd, slot, key)
                assert str(row['key_ingredient']) not in ('paneer', 'mushroom')

    def test_egg_on_monday_wednesday_friday_and_chicken_otherwise(self, days,
                                                                  chn_df):
        for wd in (0, 2, 4):
            assert int(_row(chn_df, days[wd]['nonveg_main'])['is_egg_dish']) == 1
        for wd in (1, 3):
            assert str(_row(chn_df, days[wd]['nonveg_main'])
                       ['primary_protein']) == 'chicken'

    def test_no_nonveg_biryani_ever(self, days, chn_df):
        for wd, day in days.items():
            if 'nonveg_main' not in day:
                continue
            assert int(_row(chn_df, day['nonveg_main'])
                       ['is_nonveg_biryani']) == 0, wd

    def test_three_liquid_sweets_across_the_dessert_days(self, days, chn_df):
        liquid = sum(int(_row(chn_df, d['dessert'])['is_liquid_dessert'])
                     for d in days.values() if 'dessert' in d)
        assert liquid == 3, liquid

    def test_buttermilk_on_exactly_two_days(self, days, chn_df):
        n = sum(int(_row(chn_df, d['welcome_drink'])['is_buttermilk'])
                for d in days.values() if 'welcome_drink' in d)
        assert n == 2, n

    def test_the_curd_rice_slot_serves_curd_rice(self, days, chn_df):
        for wd, day in days.items():
            if 'curd_rice' not in day:
                continue
            assert int(_row(chn_df, day['curd_rice'])['is_curd_rice']) == 1, wd


# --------------------------------------------------------------------------
# Gartner — four stated rules, all about which rice the day serves
# --------------------------------------------------------------------------
class TestGartner:
    @pytest.fixture(scope='class')
    def days(self, solved):
        return solved['Gartner'][0]

    def test_no_bread_on_the_chinese_day(self, days):
        assert 'bread' not in days[4]
        for wd in (0, 1, 2, 3):
            assert 'bread' in days[wd]

    def test_white_rice_on_wednesday_thursday_and_friday(self, days):
        assert {wd for wd, d in days.items() if 'white_rice' in d} == {2, 3, 4}

    def test_flavoured_rice_only_where_white_rice_is_not_except_friday(self,
                                                                      days):
        flavoured = {wd for wd, d in days.items() if 'rice' in d}
        assert flavoured == {0, 1, 4}
        # The client's rule in its own terms: the two never share a day except
        # on the chinese day, where both run.
        for wd, day in days.items():
            both = 'rice' in day and 'white_rice' in day
            assert both == (wd == 4), wd

    def test_fish_on_wednesday(self, days, chn_df):
        assert int(_row(chn_df, days[2]['nonveg_main'])['is_fish_dish']) == 1

    def test_and_fish_on_no_other_day(self, days, chn_df):
        """chennai.json caps seafood at one day a week; the client's rule makes
        that day Wednesday rather than leaving it to the solver."""
        for wd in (0, 1, 3, 4):
            assert int(_row(chn_df, days[wd]['nonveg_main'])['is_seafood']) == 0


# --------------------------------------------------------------------------
# World Bank — two counters
# --------------------------------------------------------------------------
class TestWorldBank:
    @pytest.fixture(scope='class')
    def full(self, solved):
        return solved['World Bank'][0]

    @pytest.fixture(scope='class')
    def combo(self, solved):
        return solved['World Bank'][1]

    def test_the_four_daily_non_veg_dishes(self, full):
        """A chicken gravy, chicken biryani, boiled egg and bone salna, every
        day. Three are pins; the fourth is the composition."""
        for wd, day in full.items():
            nonveg = {v for k, v in day.items() if k.startswith('nonveg_main')}
            assert 'chicken_biryani' in nonveg, wd
            assert 'boiled_egg' in nonveg, wd
            assert 'bone_salna' in nonveg, wd
            assert len(nonveg) == 4, (wd, nonveg)

    def test_the_fourth_dish_is_a_chicken_gravy(self, full, chn_df):
        for wd, day in full.items():
            nonveg = {v for k, v in day.items() if k.startswith('nonveg_main')}
            rest = nonveg - {'chicken_biryani', 'boiled_egg', 'bone_salna'}
            row = _row(chn_df, rest.pop())
            assert (int(row['is_north_chicken_gravy'])
                    or int(row['is_south_chicken_gravy'])), wd

    def test_a_pinned_dish_may_repeat_but_the_free_cell_may_not(self, full):
        """The pins are staples by declaration; the chicken gravy still rotates,
        which is what stops the exemption becoming a blanket one."""
        rest = []
        for _wd, day in sorted(full.items()):
            nonveg = {v for k, v in day.items() if k.startswith('nonveg_main')}
            rest.append((nonveg - {'chicken_biryani', 'boiled_egg',
                                   'bone_salna'}).pop())
        assert len(set(rest)) == len(rest), rest

    def test_chapati_and_kootu_and_buttermilk_daily(self, full, chn_df):
        for wd, day in full.items():
            assert int(_row(chn_df, day['bread'])
                       ['is_plain_phulka_chapathi']) == 1, wd
            assert _row(chn_df, day['dal'])['sub_category'] == 'kootu', wd
            assert int(_row(chn_df, day['welcome_drink'])
                       ['is_buttermilk']) == 1, wd

    def test_the_buttermilks_are_distinct_within_the_plan(self, full):
        """`scope: cooldown` drops the history ban and KEEPS unique_items."""
        drinks = [d['welcome_drink'] for d in full.values()]
        assert len(set(drinks)) == len(drinks), drinks

    def test_the_dessert_prints_the_clients_own_wording(self, full):
        for wd, day in full.items():
            assert day['dessert'] == 'Sweet/Fruit', wd

    def test_the_combo_counters_rice_is_south_every_day(self, combo, chn_df):
        for wd, day in combo.items():
            assert str(_row(chn_df, day['rice'])['cuisine_family']) \
                == 'south_indian', wd

    def test_the_combo_counter_is_not_chapati_only(self, combo):
        """It runs two breads — paratha and chapati in the sample — so the
        client-level chapati rule must be scoped to the Full Lunch counter."""
        breads = {v for d in combo.values() for k, v in d.items()
                  if k.startswith('bread')}
        assert len(breads) > 1


# --------------------------------------------------------------------------
# ICON Chn — four counters
# --------------------------------------------------------------------------
class TestIconChn:
    @pytest.fixture(scope='class')
    def counters(self, solved):
        return solved['ICON Chn']

    def test_every_counter_plans(self, counters):
        assert all(len(c) == 5 for c in counters)

    def test_premium_serves_its_three_dishes_on_mon_wed_fri_only(self,
                                                                 counters):
        premium = counters[0]
        for wd in (0, 2, 4):
            nonveg = {v for k, v in premium[wd].items()
                      if k.startswith('nonveg_main')}
            assert nonveg == {'chicken_biryani', 'boiled_egg', 'bone_salna'}, wd
        for wd in (1, 3):
            assert not [k for k in premium[wd] if k.startswith('nonveg_main')]

    def test_dal_and_veg_dry_alternate_and_never_share_a_day(self, counters):
        for idx in (0, 1):
            for wd, day in counters[idx].items():
                assert ('dal' in day) != ('veg_dry' in day), (idx, wd)
            assert {wd for wd, d in counters[idx].items() if 'dal' in d} == {1, 3}

    def test_the_dal_is_a_kootu_on_both_lunch_counters(self, counters, chn_df):
        for idx in (0, 1):
            for wd, day in counters[idx].items():
                if 'dal' not in day:
                    continue
                assert _row(chn_df, day['dal'])['sub_category'] == 'kootu'

    def test_economy_and_roti_serve_an_egg_gravy_mon_wed_chicken_otherwise(
            self, counters, chn_df):
        for idx in (1, 3):
            days = counters[idx]
            for wd in (0, 2):
                row = _row(chn_df, days[wd]['nonveg_main'])
                assert int(row['is_egg_dish']) == 1, (idx, wd)
                assert int(row['is_nonveg_gravy']) == 1, (idx, wd)
            for wd in (1, 3, 4):
                row = _row(chn_df, days[wd]['nonveg_main'])
                assert (int(row['is_north_chicken_gravy'])
                        or int(row['is_south_chicken_gravy'])), (idx, wd)

    def test_the_bread_counters_serve_chapati(self, counters, chn_df):
        for idx in (0, 3):
            for wd, day in counters[idx].items():
                assert int(_row(chn_df, day['bread'])
                           ['is_plain_phulka_chapathi']) == 1, (idx, wd)

    def test_the_rice_combo_alternates_gravy_and_dry(self, counters):
        rice_combo = counters[2]
        assert {wd for wd, d in rice_combo.items() if 'veg_dry' in d} == {2, 4}
        assert {wd for wd, d in rice_combo.items()
                if 'veg_gravy' in d} == {0, 1, 3}

    def test_the_rice_combo_serves_a_biryani_on_wednesday(self, counters,
                                                          chn_df):
        assert int(_row(chn_df, counters[2][2]['rice'])
                   ['is_biryani_item']) == 1

    def test_the_rice_combo_is_left_out_of_the_shared_sync(self):
        """'rice combo counter is not linked to the shared items list'. The
        exclusion is declared in the client's rules file and read by the planner
        through `/client-config`; `shared_categories` itself is client-wide."""
        from src.menu_rules import MenuRuleLoader
        excluded = MenuRuleLoader().get_shared_category_exclusions('ICON Chn')
        assert excluded == ['Rice Combo']


# --------------------------------------------------------------------------
# The planner's own multi-counter loop, which no per-counter test exercises
# --------------------------------------------------------------------------
class TestTheMultiCounterLoop:
    """`app.py` solves the primary, extracts its shared-slot dishes, and passes
    them to every later counter. Solving each counter alone — which is what the
    rest of this file does — never sends those pins, so the whole feature was
    untested end to end. It failed the first time it was run this way.
    """

    @pytest.fixture(scope='class')
    def loop(self, request):
        """Reproduce the planner loop for ICON Chn, exactly as app.py does."""
        from ui.formatters import shared_items_from_solution
        import api.app as api_app
        import src.db as db_mod
        from api.rate_limit import reset_for_tests

        fake = FakeSupabase(seed={
            'clients': [dict(c) for c in CLIENTS.values()],
            'app_settings': [], 'menu_history': [], 'week_signatures': [],
        })
        previous = getattr(db_mod, '_sb_client', None)
        db_mod._sb_client = fake
        api_app._client_loader = None
        api_app.reset_caches()
        api_app.app.config['TESTING'] = True
        cl = api_app.app.test_client()
        try:
            reset_for_tests()
            cfg = cl.get('/api/v1/client-config/ICON Chn').get_json()
            cats = cfg.get('shared_categories') or []
            excluded = set(cfg.get('shared_categories_excluded_counters') or [])
            names = [c.get('name') for c in cfg.get('counters') or []]
            shared, out = [], {}
            for i, cname in enumerate(names):
                send = shared if (i > 0 and cname not in excluded) else None
                payload = {'client_name': 'ICON Chn', 'start_date': MONDAY,
                           'num_days': 5, 'time_limit_seconds': TIME_LIMIT,
                           'counter_index': i}
                if send:
                    payload['shared_items'] = send
                reset_for_tests()
                resp = cl.post('/api/v1/plan', json=payload)
                body = resp.get_json() or {}
                out[cname] = (resp.status_code, body)
                if i == 0 and cats:
                    shared = shared_items_from_solution(
                        body.get('solution', {}), cats)
            yield out, cats, excluded, names
        finally:
            db_mod._sb_client = previous
            api_app._client_loader = None
            api_app.reset_caches()

    @staticmethod
    def _dishes(body):
        return {iso: {s: it.get('item_base')
                      for s, it in (d.get('items') or {}).items()}
                for iso, d in (body.get('solution') or {}).items()}

    def test_every_counter_still_returns_a_plan(self, loop):
        out, _cats, _excl, names = loop
        for cname in names:
            assert out[cname][0] == 200, (cname, out[cname][1].get('error'))

    def test_the_shared_slots_are_actually_synced(self, loop):
        """Economy Lunch takes the primary's dish for every shared slot they
        both run — the feature doing its job."""
        out, cats, _excl, names = loop
        primary = self._dishes(out[names[0]][1])
        econ = self._dishes(out['Economy Lunch'][1])
        checked = 0
        for base in cats:
            days = [i for i in primary
                    if base in primary[i] and base in econ.get(i, {})]
            if not days:
                continue
            checked += 1
            assert all(primary[i][base] == econ[i][base] for i in days), base
        assert checked >= 5, checked

    def test_the_excluded_counter_is_left_alone(self, loop):
        """'rice combo counter is not linked to the shared items list'."""
        out, cats, excl, names = loop
        assert 'Rice Combo' in excl
        primary = self._dishes(out[names[0]][1])
        rice = self._dishes(out['Rice Combo'][1])
        shared_hits = sum(
            primary[i][base] == rice[i][base]
            for base in cats for i in primary
            if base in primary[i] and base in rice.get(i, {}))
        assert shared_hits == 0, shared_hits

    def test_a_counter_that_cannot_take_the_pins_falls_back(self, loop):
        """The documented contract is that the sync NEVER makes a counter
        INFEASIBLE (note 22), and it did: Roti Combo runs four colour cells and
        the primary pins three of them, so a day whose pinned bread, gravy and
        dessert carry two colours between them cannot reach the three distinct
        the city asks for. Each pin is individually eligible, so nothing catches
        it in advance — the counter is re-solved without the sync instead, and
        says so.
        """
        out, _cats, _excl, _names = loop
        status, body = out['Roti Combo']
        assert status == 200
        assert any('Cross-counter sync skipped' in str(w)
                   for w in (body.get('pool_warnings') or [])), \
            body.get('pool_warnings')
