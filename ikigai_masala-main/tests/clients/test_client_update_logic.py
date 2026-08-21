"""Six clients' stated rules, against real solves.

AT&T, Bakertilly, Citrix, Moengage and Tekion CHN came from the client's
`client_update.xlsx` `rules` sheet; Corning Chakan came from its own list. Each
one's stated logic is checked against a real plan, so a rule that loads but never
bites fails here rather than looking configured.

The counters mirror the live `clients` rows. Requirements deliberately left to
existing machinery are asserted anyway when they are observable — 'daily curd
except on the biryani day it is raita' is the city ruleset's `curd_raita_logic`,
not a per-client rule, and the point of testing it is that the client's
requirement is met however it is met.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'
TIME_LIMIT = 40
WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri']


def _client(name, city, categories, slot_counts, theme_map,
            serve_weekends=False):
    return {
        'name': name, 'version': 1, 'city': city,
        'serve_weekends': serve_weekends,
        'item_cooldown_days': 20, 'source_pools': [],
        'counters': [{
            'name': 'Counter 1', 'theme_map': theme_map,
            'categories': categories, 'slot_counts': slot_counts,
        }],
    }


CLIENTS = {
    'AT&T': _client(
        'AT&T', 'Bangalore',
        ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'sambar',
         'rasam', 'dessert', 'curd_side', 'nonveg_main', 'white_rice'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1, 'sambar': 1,
         'dessert': 1, 'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1,
         'nonveg_main': 1},
        {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'biryani',
         'thursday': 'north', 'friday': 'mix'}),
    'Bakertilly': _client(
        'Bakertilly', 'Bangalore',
        ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'sambar',
         'rasam', 'dessert', 'curd_side', 'nonveg_main', 'white_rice'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1, 'sambar': 1,
         'dessert': 1, 'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1,
         'nonveg_main': 2},
        {'monday': 'mix', 'tuesday': 'south', 'wednesday': 'biryani',
         'thursday': 'mix', 'friday': 'north'}),
    'Citrix': _client(
        'Citrix', 'Bangalore',
        ['welcome_drink', 'salad', 'bread', 'rice', 'white_rice', 'veg_dry',
         'veg_gravy', 'dal', 'rasam', 'dessert', 'curd_side', 'papad',
         'pickle', 'nonveg_main'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1, 'dessert': 1,
         'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1, 'nonveg_main': 1,
         'welcome_drink': 1},
        {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'mix',
         'thursday': 'mix', 'friday': 'biryani'}),
    # Two non-veg dishes a day and a compulsory egg rule. The live row's
    # `slot_counts` holds only `nonveg_main: 2` and its `theme_map` is empty
    # (both recorded in docs/pending_config_changes.md as DB gaps); the rest is
    # filled in here so the counter is actually exercised.
    'Moengage': _client(
        'Moengage', 'Bangalore',
        ['bread', 'veg_dry', 'rice', 'veg_gravy', 'dal', 'sambar',
         'nonveg_main', 'rasam', 'white_rice', 'papad', 'pickle', 'curd_side',
         'dessert', 'welcome_drink'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'sambar': 1,
         'dessert': 1, 'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1,
         'nonveg_main': 2, 'welcome_drink': 1},
        {'monday': 'mix', 'tuesday': 'chinese', 'wednesday': 'biryani',
         'thursday': 'south', 'friday': 'north'}),
    # Pune site, seven days a week, and the only counter with a `soup` station
    # opposite a `dessert` one. `starter` is added here because the Thursday
    # chaat rule needs it and the live row has no such category yet — the config
    # file and docs/pending_config_changes.md both record that as a DB change.
    'Corning Chakan': _client(
        'Corning Chakan', 'Pune',
        ['soup', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'dessert',
         'white_rice', 'starter'],
        {'dal': 1, 'rice': 1, 'soup': 1, 'bread': 1, 'dessert': 1,
         'veg_dry': 1, 'veg_gravy': 1, 'starter': 1},
        {'monday': 'north', 'tuesday': 'north', 'wednesday': 'south',
         'thursday': 'north', 'friday': 'mix'},
        serve_weekends=True),
    'Tekion CHN': _client(
        'Tekion CHN', 'Chennai',
        ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'sambar',
         'rasam', 'dessert', 'curd_side', 'nonveg_main', 'white_rice'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'rasam': 1, 'salad': 1, 'sambar': 1,
         'dessert': 1, 'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1,
         'nonveg_main': 1},
        # Chennai's OWN map, as the live row has it. The client's rules copy
        # Tekion BLR but its themes do NOT, so the weekday rules land on
        # different themes here and each was checked against what Chennai can
        # serve on that day.
        {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'south',
         'thursday': 'biryani', 'friday': 'north'}),
}


@pytest.fixture(scope='module')
def blr_df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Bangalore'))


@pytest.fixture(scope='module')
def chn_df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Chennai'))


@pytest.fixture
def api(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS.values()],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _plan(api, name, start=MONDAY, num_days=5):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api.app.test_client().post('/api/v1/plan', json={
        'client_name': name, 'start_date': start, 'num_days': num_days,
        'time_limit_sec': TIME_LIMIT})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['solution']


# ----- shared readers -----

def _row(df, base):
    hit = df[df['item'].astype(str).str.strip() == base]
    return None if hit.empty else hit.iloc[0]


def _flag(df, base, col):
    r = _row(df, base)
    return r is not None and pd.to_numeric(r.get(col), errors='coerce') == 1


def _attr(df, base, col):
    r = _row(df, base)
    return '' if r is None else str(r.get(col, '')).strip().lower()


def _by_day(solution, prefix, week=None):
    """weekday -> list of item_bases in slots whose id starts with *prefix*."""
    week = week or WEEKDAYS
    out = {}
    for i, day in enumerate(solution.values()):
        items = day.get('items') or {}
        out[week[i]] = [c['item_base'] for s, c in items.items()
                        if s.startswith(prefix)]
    return out


def _all_bases(day):
    return [c['item_base'] for c in (day.get('items') or {}).values()]


def _days_matching(df, solution, pred):
    return sum(1 for day in solution.values()
               if any(pred(df, b) for b in _all_bases(day)))


# ---------------------------------------------------------------- AT&T


@pytest.mark.slow
class TestAttAndT:
    """'Indian bread will be chapathi and flavour chapathi only. Daily curd
    except on biryani day it is raita. Paneer dish once a week. Soya or kofta
    once a week. Weekly 3 days pulav in flavour rice.'"""

    def test_bread_is_always_a_chapati_or_phulka(self, api, blr_df):
        """Asserted on the FLAG, not the dish name. `bread_chapati_only` selects
        on `is_plain_phulka_chapathi`, which `scripts/bread_form_flags.py` made
        definitional in both directions — so a `tawa_roti` or `wheat_palak_roti`
        is a chapati-class bread with no "chapati" in its name, while an
        `appam_chapati` has the word and is not one."""
        sol = _plan(api, 'AT&T')
        breads = _by_day(sol, 'bread')
        assert all(breads.values()), breads
        for day, items in breads.items():
            for b in items:
                assert _flag(blr_df, b, 'is_plain_phulka_chapathi'), \
                    f'{day}: {b} is not a chapati, phulka or wheat roti'

    def test_paneer_exactly_one_day(self, api, blr_df):
        sol = _plan(api, 'AT&T')
        days = _days_matching(
            blr_df, sol, lambda d, b: _attr(d, b, 'primary_protein') == 'paneer')
        assert days == 1, f'paneer on {days} day(s), want 1'

    def test_soya_or_kofta_exactly_one_day(self, api, blr_df):
        sol = _plan(api, 'AT&T')
        days = _days_matching(
            blr_df, sol,
            lambda d, b: (_attr(d, b, 'key_ingredient') == 'soy'
                          or _flag(d, b, 'is_veg_kofta_gravy')))
        assert days == 1, f'soya/kofta on {days} day(s), want 1'

    def test_three_pulao_days_in_the_flavoured_rice_slot(self, api, blr_df):
        sol = _plan(api, 'AT&T')
        rice = _by_day(sol, 'rice')
        days = sum(1 for items in rice.values()
                   if any(_flag(blr_df, b, 'is_pulao') for b in items))
        assert days == 3, f'pulao on {days} rice day(s), want 3: {rice}'

    def test_raita_on_the_biryani_day_and_curd_on_the_rest(self, api, blr_df):
        """Not a per-client rule — `curd_raita_logic` in the city ruleset does
        this. Asserted because it is the client's requirement, however it is met.
        """
        sol = _plan(api, 'AT&T')
        side = _by_day(sol, 'curd_side')
        assert all(side.values()), side
        # Wednesday is AT&T's biryani day.
        assert any(_flag(blr_df, b, 'is_raita') for b in side['wed']), side['wed']
        for day in ('mon', 'tue', 'thu', 'fri'):
            assert any(_flag(blr_df, b, 'is_plain_curd')
                       or _flag(blr_df, b, 'is_raita')
                       for b in side[day]), (day, side[day])


# ---------------------------------------------------------- Bakertilly


@pytest.mark.slow
class TestBakertilly:
    """'Weekly 1 paneer. On biryani day we will only serve indian bread, rasam,
    veg curry, flavoured rice, white rice and salad — other will be blank. Only
    on biryani day we will have chicken dry also. Daily curd except of biryani
    day it is raita.'"""

    def test_the_biryani_day_stands_the_listed_stations_down(self, api):
        sol = _plan(api, 'Bakertilly')
        days = list(sol.values())
        wed = days[2]                      # Wednesday is the biryani day
        slots = set((wed.get('items') or {}).keys())
        for gone in ('veg_dry', 'dal', 'sambar', 'dessert'):
            assert not [s for s in slots if s.startswith(gone)], \
                f'{gone} should be blank on the biryani day: {sorted(slots)}'
        for kept in ('bread', 'rasam', 'veg_gravy', 'rice', 'salad'):
            assert [s for s in slots if s.startswith(kept)], \
                f'{kept} should still be served on the biryani day'

    def test_the_stood_down_stations_run_on_every_other_day(self, api):
        sol = _plan(api, 'Bakertilly')
        for i, day in enumerate(sol.values()):
            if i == 2:
                continue
            slots = set((day.get('items') or {}).keys())
            for base in ('veg_dry', 'dal', 'sambar', 'dessert'):
                assert [s for s in slots if s.startswith(base)], \
                    f'{WEEKDAYS[i]}: {base} missing'

    def test_a_dry_nonveg_lands_on_the_biryani_day_and_nowhere_else(
            self, api, blr_df):
        sol = _plan(api, 'Bakertilly')
        nv = _by_day(sol, 'nonveg_main')

        def dry(b):
            return (_flag(blr_df, b, 'is_nonveg_dry')
                    or _flag(blr_df, b, 'is_tandoor_nonveg_dry'))

        assert any(dry(b) for b in nv['wed']), nv['wed']
        for day in ('mon', 'tue', 'thu', 'fri'):
            assert not any(dry(b) for b in nv[day]), (day, nv[day])

    def test_paneer_exactly_one_day(self, api, blr_df):
        sol = _plan(api, 'Bakertilly')
        days = _days_matching(
            blr_df, sol, lambda d, b: _attr(d, b, 'primary_protein') == 'paneer')
        assert days == 1, f'paneer on {days} day(s), want 1'

    def test_curd_side_is_a_raita_on_the_biryani_day(self, api, blr_df):
        """The client's two rules disagree about the biryani day; the curd rule
        names it explicitly, so `curd_side` is kept there as a raita."""
        sol = _plan(api, 'Bakertilly')
        side = _by_day(sol, 'curd_side')
        assert side['wed'], 'curd_side should still run on the biryani day'
        assert any(_flag(blr_df, b, 'is_raita') for b in side['wed']), side['wed']


# --------------------------------------------------------------- Citrix


@pytest.mark.slow
class TestCitrix:
    """'Welcome drink will be buttermilk only. If veg gravy is north then veg dry
    should be north. Phulka or chapati only to be served indian bread. Flavour
    rice and veg gravy should be of the same region. Nonveg main: Mon & Wed
    chicken gravy, Tue egg curry, Friday biryani only. The region should
    alternate from south and north, should not be the same on 2 continuous days
    for flavour rice, veg gravy and veg dry.'"""

    def test_the_welcome_drink_is_buttermilk_every_day(self, api, blr_df):
        sol = _plan(api, 'Citrix')
        drinks = _by_day(sol, 'welcome_drink')
        assert all(drinks.values()), drinks
        for day, items in drinks.items():
            assert all(_flag(blr_df, b, 'is_buttermilk') for b in items), \
                f'{day}: {items} is not buttermilk'

    def test_bread_is_always_a_chapati_or_phulka(self, api, blr_df):
        sol = _plan(api, 'Citrix')
        breads = _by_day(sol, 'bread')
        assert all(breads.values()), breads
        for day, items in breads.items():
            for b in items:
                assert _flag(blr_df, b, 'is_plain_phulka_chapathi'), \
                    f'{day}: {b} is not a chapati, phulka or wheat roti'

    def test_nonveg_follows_the_stated_weekday_schedule(self, api, blr_df):
        sol = _plan(api, 'Citrix')
        nv = _by_day(sol, 'nonveg_main')

        def chicken_gravy(b):
            return ((_flag(blr_df, b, 'is_north_chicken_gravy')
                     or _flag(blr_df, b, 'is_south_chicken_gravy'))
                    and not _flag(blr_df, b, 'is_egg_dish'))

        assert any(chicken_gravy(b) for b in nv['mon']), nv['mon']
        assert any(chicken_gravy(b) for b in nv['wed']), nv['wed']
        assert any(_flag(blr_df, b, 'is_egg_dish') for b in nv['tue']), nv['tue']
        assert any(_flag(blr_df, b, 'is_nonveg_biryani') for b in nv['fri']), \
            nv['fri']

    def test_thursday_serves_no_nonveg_at_all(self, api):
        """The client named four of five days and confirmed the fifth is
        deliberate: Thursday's non-veg station stands down rather than serving an
        unscheduled dish."""
        sol = _plan(api, 'Citrix')
        nv = _by_day(sol, 'nonveg_main')
        assert not nv['thu'], nv
        for day in ('mon', 'tue', 'wed', 'fri'):
            assert nv[day], (day, nv)

    def test_the_biryani_is_not_spent_before_the_biryani_day(
            self, api, blr_df):
        """A `mix` day is not narrowed by the theme filter at all, so without
        `citrix_biryani_only_on_biryani_day` the solver could serve the week's
        one chicken biryani on a Monday and leave Friday's mandate
        unsatisfiable."""
        sol = _plan(api, 'Citrix')
        nv = _by_day(sol, 'nonveg_main')
        for day in ('mon', 'tue', 'wed', 'thu'):
            assert not any(_flag(blr_df, b, 'is_nonveg_biryani')
                           for b in nv[day]), (day, nv[day])

    def test_rice_gravy_and_veg_dry_agree_on_a_region_most_days(
            self, api, blr_df):
        """SOFT rules ('if I give south I can use north fallback'), so this
        asserts the preference took effect, not that it is inviolable: on a day
        where all three slots carry a listed region, they should agree."""
        sol = _plan(api, 'Citrix')
        agreed = considered = 0
        for day in sol.values():
            items = day.get('items') or {}
            regions = {}
            for slot, cand in items.items():
                base = slot.split('__')[0]
                if base not in ('rice', 'veg_gravy', 'veg_dry'):
                    continue
                fam = _attr(blr_df, cand['item_base'], 'cuisine_family')
                if fam in ('north_indian', 'south_indian'):
                    regions.setdefault(base, set()).add(fam)
            if len(regions) < 2:
                continue
            considered += 1
            if len(set().union(*regions.values())) == 1:
                agreed += 1
        assert considered, 'no day had two comparable regional slots'
        assert agreed >= considered - 1, \
            f'only {agreed} of {considered} comparable days agreed on a region'

    def test_the_plate_region_does_not_repeat_on_consecutive_days(
            self, api, blr_df):
        """The alternation half. Soft as well, so one exception is tolerated —
        Friday's biryani day narrows the rice and can force a repeat."""
        sol = _plan(api, 'Citrix')
        seq = []
        for day in sol.values():
            fams = {_attr(blr_df, c['item_base'], 'cuisine_family')
                    for s, c in (day.get('items') or {}).items()
                    if s.split('__')[0] == 'rice'}
            fams &= {'north_indian', 'south_indian'}
            seq.append(next(iter(fams), None))
        runs = sum(1 for a, b in zip(seq, seq[1:])
                   if a is not None and a == b)
        assert runs <= 1, f'rice region repeated on {runs} adjacent pairs: {seq}'


# ----------------------------------------------------------- Tekion CHN


@pytest.mark.slow
class TestTekionChn:
    """'Its rules are the same as Tekion BLR.' Run against Tekion BLR's theme
    map, which is what "the same rules" needs (see the config file's header)."""

    def test_the_counter_plans(self, api):
        sol = _plan(api, 'Tekion CHN')
        assert len(sol) == 5
        for day in sol.values():
            assert day.get('items')

    def test_every_dish_comes_from_the_chennai_list(self, api, chn_df):
        """Const slots are excluded: `white_rice`, `papad` and `pickle` are
        stamped labels ("steamed rice"), not solved ontology rows."""
        from src.constants import CONST_SLOTS
        sol = _plan(api, 'Tekion CHN')
        names = set(chn_df['item'].astype(str).str.strip())
        for day in sol.values():
            for slot, cand in (day.get('items') or {}).items():
                if slot.split('__')[0] in CONST_SLOTS:
                    continue
                assert cand['item_base'] in names, \
                    f'{cand["item_base"]} is not a Chennai dish'

    def test_nonveg_runs_on_mon_wed_fri_only(self, api):
        sol = _plan(api, 'Tekion CHN')
        nv = _by_day(sol, 'nonveg_main')
        assert nv['mon'] and nv['wed'] and nv['fri'], nv
        assert not nv['tue'] and not nv['thu'], nv

    def test_chicken_gravy_mon_and_wed_biryani_friday(self, api, chn_df):
        sol = _plan(api, 'Tekion CHN')
        nv = _by_day(sol, 'nonveg_main')

        def chicken_gravy(b):
            return ((_flag(chn_df, b, 'is_north_chicken_gravy')
                     or _flag(chn_df, b, 'is_south_chicken_gravy'))
                    and not _flag(chn_df, b, 'is_egg_dish'))

        assert any(chicken_gravy(b) for b in nv['mon']), nv['mon']
        assert any(chicken_gravy(b) for b in nv['wed']), nv['wed']
        assert any(_flag(chn_df, b, 'is_nonveg_biryani') for b in nv['fri']), \
            nv['fri']

    def test_no_mushroom_anywhere(self, api, chn_df):
        sol = _plan(api, 'Tekion CHN')
        for day in sol.values():
            for b in _all_bases(day):
                assert 'mushroom' not in (
                    _attr(chn_df, b, 'key_ingredient')
                    + _attr(chn_df, b, 'primary_protein')), b

    def test_a_khichdi_lands_on_thursday(self, api, chn_df):
        sol = _plan(api, 'Tekion CHN')
        rice = _by_day(sol, 'rice')
        assert any(_flag(chn_df, b, 'is_liquid_rice') for b in rice['thu']), \
            rice
        # ...and it is the week's only liquid rice.
        days = sum(1 for items in rice.values()
                   if any(_flag(chn_df, b, 'is_liquid_rice') for b in items))
        assert days == 1, f'liquid rice on {days} day(s), want 1: {rice}'

    def test_no_chinese_dish_is_ever_served(self, api, chn_df):
        """The client's decision: no Chinese at the Chennai site. BLR's two
        Chinese-Tuesday rules are absent, and Tuesday is a `mix` day here — which
        the theme filter does not narrow at all, so nothing but this assertion
        would have noticed a manchurian turning up."""
        sol = _plan(api, 'Tekion CHN')
        for day in sol.values():
            for b in _all_bases(day):
                assert _attr(chn_df, b, 'cuisine_family') != 'chinese', b

    def test_a_paneer_gravy_lands_on_wednesday(self, api, chn_df):
        """Wednesday is a SOUTH day at this site and Chennai has one south
        paneer gravy, so the rule is satisfiable exactly once per cooldown
        window — this asserts the first week, which is the week it can meet."""
        sol = _plan(api, 'Tekion CHN')
        gravy = _by_day(sol, 'veg_gravy')
        assert any(_flag(chn_df, b, 'is_paneer_gravy') for b in gravy['wed']), \
            gravy

    def test_bread_is_always_a_chapati_or_phulka(self, api, chn_df):
        sol = _plan(api, 'Tekion CHN')
        breads = _by_day(sol, 'bread')
        assert all(breads.values()), breads
        for day, items in breads.items():
            for b in items:
                assert _flag(chn_df, b, 'is_plain_phulka_chapathi'), \
                    f'{day}: {b} is not a chapati, phulka or wheat roti'


# --------------------------------------------------------- Corning Chakan

FULL_WEEK = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


@pytest.fixture(scope='module')
def sol():
    """One seven-day Corning Chakan solve, shared by the whole class.

    Seeded and restored by hand rather than through the function-scoped `api`
    fixture: a module-scoped fixture cannot depend on a function-scoped one
    (`api` uses monkeypatch), and thirteen seven-day solves at 40s each is not a
    price worth paying for isolation these read-only assertions do not need. Same
    pattern as `test_pune_client_logic.py`'s shared plan.
    """
    import src.db as db_mod
    import api.app as api_app
    from api.rate_limit import reset_for_tests

    fake = FakeSupabase(seed={
        'clients': [dict(c) for c in CLIENTS.values()],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    })
    old_sb = getattr(db_mod, '_sb_client', None)
    db_mod._sb_client = fake
    api_app._client_loader = None
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    try:
        reset_for_tests()
        resp = api_app.app.test_client().post('/api/v1/plan', json={
            'client_name': 'Corning Chakan', 'start_date': MONDAY,
            'num_days': 7, 'time_limit_sec': TIME_LIMIT})
        assert resp.status_code == 200, resp.get_json()
        yield resp.get_json()['solution']
    finally:
        db_mod._sb_client = old_sb
        api_app._client_loader = None
        api_app.reset_caches()


@pytest.fixture(scope='module')
def pune_df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Pune'))


@pytest.mark.slow
class TestCorningChakan:
    """The fourteen rules the client stated for its Pune site, over a seven-day
    plan (`serve_weekends` is true, and the soup schedule needs Sat and Sun).

    Three of the fourteen are asserted as *absences of a rule*: 'sweet and soup
    on alternate days' is what the two day-restrictions already produce, 'soya
    can be served as one of the vegetable options' is permission rather than a
    constraint, and 'kabuli chana max once a week' is Pune's own city rule.
    """


    def test_soup_only_on_tue_thu_sat_sun(self, sol):
        soup = _by_day(sol, 'soup', FULL_WEEK)
        for day in ('tue', 'thu', 'sat', 'sun'):
            assert soup[day], f'{day} should carry a soup: {soup}'
        for day in ('mon', 'wed', 'fri'):
            assert not soup[day], f'{day} should have no soup: {soup}'

    def test_sweets_only_on_mon_wed_fri(self, sol):
        sweet = _by_day(sol, 'dessert', FULL_WEEK)
        for day in ('mon', 'wed', 'fri'):
            assert sweet[day], f'{day} should carry a sweet: {sweet}'
        for day in ('tue', 'thu', 'sat', 'sun'):
            assert not sweet[day], f'{day} should have no sweet: {sweet}'

    def test_sweet_and_soup_alternate(self, sol):
        """The client's third rule, which needs no rule of its own: with the two
        restrictions above, every day carries exactly one of the pair."""
        soup = _by_day(sol, 'soup', FULL_WEEK)
        sweet = _by_day(sol, 'dessert', FULL_WEEK)
        for day in FULL_WEEK:
            assert bool(soup[day]) != bool(sweet[day]), \
                f'{day}: soup={soup[day]} sweet={sweet[day]}'

    def test_no_liquid_sweet_is_ever_served(self, sol, pune_df):
        for day in sol.values():
            for b in _all_bases(day):
                assert not _flag(pune_df, b, 'is_liquid_dessert'), b

    def test_black_dal_at_most_once(self, sol, pune_df):
        dal = _by_day(sol, 'dal', FULL_WEEK)
        days = sum(1 for items in dal.values()
                   if any(_flag(pune_df, b, 'is_black_dal') for b in items))
        assert days <= 1, f'black dal on {days} days: {dal}'

    def test_legume_and_kabuli_gravies_at_most_once_each(self, sol, pune_df):
        """Pune's own ruleset, asserted here because it is the client's rule."""
        gravy = _by_day(sol, 'veg_gravy', FULL_WEEK)
        for flag in ('is_whole_legume_based', 'is_kabuli_chana_gravy'):
            days = sum(1 for items in gravy.values()
                       if any(_flag(pune_df, b, flag) for b in items))
            assert days <= 1, f'{flag} on {days} days: {gravy}'

    def test_sprouts_gravy_at_most_twice(self, sol):
        gravy = _by_day(sol, 'veg_gravy', FULL_WEEK)
        days = sum(1 for items in gravy.values()
                   if any('sprout' in b or 'matki' in b for b in items))
        assert days <= 2, f'sprouts gravy on {days} days: {gravy}'

    def test_exactly_one_paneer_gravy_day(self, sol, pune_df):
        gravy = _by_day(sol, 'veg_gravy', FULL_WEEK)
        days = sum(1 for items in gravy.values()
                   if any(_flag(pune_df, b, 'is_paneer_gravy') for b in items))
        assert days == 1, f'paneer gravy on {days} days: {gravy}'

    def test_paneer_or_kofta_on_at_most_one_day(self, sol, pune_df):
        """The two premium rules read together: the paneer gravy IS the week's
        one paneer-or-kofta dish, so a kofta must not add a second day."""
        days = _days_matching(
            pune_df, sol,
            lambda d, b: (_attr(d, b, 'key_ingredient') == 'paneer'
                          or _flag(d, b, 'is_veg_kofta_gravy')))
        assert days <= 1, f'paneer/kofta on {days} days'

    def test_mixedveg_kurma_kofta_at_most_twice(self, sol, pune_df):
        gravy = _by_day(sol, 'veg_gravy', FULL_WEEK)
        days = sum(
            1 for items in gravy.values()
            if any(_flag(pune_df, b, f) for b in items
                   for f in ('is_mixedveg_gravy', 'is_kurma_gravy',
                             'is_veg_kofta_gravy')))
        assert days <= 2, f'mixedveg/kurma/kofta on {days} days: {gravy}'

    def test_leafy_veg_dry_twice_a_week(self, sol, pune_df):
        """The one rule that overrides Pune's rulebook: R31 caps leafy dry at
        one day and the 15-day cadence allows one per three weeks, both of which
        this client's config lifts."""
        dry = _by_day(sol, 'veg_dry', FULL_WEEK)
        days = sum(1 for items in dry.values()
                   if any(_flag(pune_df, b, 'is_leafy_based_dish')
                          for b in items))
        assert days == 2, f'leafy veg dry on {days} days: {dry}'

    def test_a_chaat_starter_on_thursday_and_no_other_day(self, sol):
        starter = _by_day(sol, 'starter', FULL_WEEK)
        assert starter['thu'], f'Thursday should carry a starter: {starter}'
        for b in starter['thu']:
            assert 'chaat' in b or 'chat' in b, f'{b} is not a chaat'
        for day in FULL_WEEK:
            if day != 'thu':
                assert not starter[day], f'{day} should have no starter'

    def test_every_dish_comes_from_the_pune_list(self, sol, pune_df):
        from src.constants import CONST_SLOTS
        names = set(pune_df['item'].astype(str).str.strip())
        for day in sol.values():
            for slot, cand in (day.get('items') or {}).items():
                if slot.split('__')[0] in CONST_SLOTS:
                    continue
                assert cand['item_base'] in names, cand['item_base']


# --------------------------------------------------------------- Moengage


@pytest.mark.slow
class TestMoengage:
    """'Mutton once a month. Aloo once a week. Banned in main course: pumpkin,
    brinjal, yam and bisibele bath. Week 1-2 egg non-veg main is compulsory.'"""

    def test_an_egg_dish_lands_on_one_or_two_days(self, api, blr_df):
        sol = _plan(api, 'Moengage')
        nv = _by_day(sol, 'nonveg_main')
        days = sum(1 for items in nv.values()
                   if any(_flag(blr_df, b, 'is_egg_dish') for b in items))
        assert 1 <= days <= 2, f'egg on {days} day(s), want 1-2: {nv}'

    def test_none_of_the_banned_ingredients_appears(self, api, blr_df):
        sol = _plan(api, 'Moengage')
        banned = {'pumpkin', 'brinjal', 'eggplant', 'yam', 'elephant_yam'}
        for day in sol.values():
            for b in _all_bases(day):
                assert _attr(blr_df, b, 'key_ingredient') not in banned, b
                assert _attr(blr_df, b, 'primary_protein') not in banned, b

    def test_no_bisibele_bath(self, api):
        sol = _plan(api, 'Moengage')
        for day in sol.values():
            for b in _all_bases(day):
                assert 'bisibele' not in b and 'bisi_bele' not in b, b

    def test_aloo_on_at_most_one_day(self, api, blr_df):
        """'Aloo (Potato): Once a week' is a LIMIT, not a requirement — it sits
        in a list beside "Mutton: Once a month" and a banned-ingredient set, all
        of which cap rather than mandate. So the rule is `max: 1` and a week with
        no potato at all is compliant; asserting exactly one was reading the
        client's sentence as a floor it does not carry."""
        sol = _plan(api, 'Moengage')
        days = _days_matching(
            blr_df, sol, lambda d, b: _attr(d, b, 'key_ingredient') == 'potato')
        assert days <= 1, f'potato on {days} day(s), want at most 1'
