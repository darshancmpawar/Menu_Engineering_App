"""The five NCR sites' client-specific logics, against real solves.

`data/configs/client_rules.json` encodes the lunch-relevant logics from the
client's `Site_Specific_Menu_items_logic` workbook (sheet -> client name:
'Stryker Sector 59' -> Stryker NCR, 'Seimens' -> Siemens, 'Airtel Plot 5' ->
Airtel Noida, 'Sinch' -> Sinch NCR, 'Junglee' -> Junglee Games). This runs each
counter and checks the rule that should bite actually does.

The counters mirror the live `clients` rows (city NCR, source_pools=[] -> the F5
fallback plans them from the full NCR list). Deferred logics (fish cadence,
'Thursday special', breakfast/snacks items, the chaat slot Junglee lacks) are
documented as `_comment`s in client_rules.json and are not asserted here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'
TIME_LIMIT = 30
WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri']


def _north():
    return {d: 'north' for d in
            ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')}


def _counter(name, categories, slot_counts, theme_map=None):
    return {
        'name': name, 'version': 1, 'city': 'NCR', 'serve_weekends': False,
        'item_cooldown_days': 20, 'source_pools': [],
        'counters': [{
            'name': 'Counter 1',
            'theme_map': theme_map or _north(),
            'categories': categories, 'slot_counts': slot_counts,
        }],
    }


CLIENTS = {
    'Stryker NCR': _counter(
        'Stryker NCR',
        ['welcome_drink', 'salad', 'bread', 'rice', 'veg_dry', 'veg_gravy',
         'dal', 'dessert', 'curd_side', 'nonveg_main', 'white_rice'],
        # bread 2: 'indian bread 1 tawa roti, bread 2 follows rules' (the live
        # DB has bread 1 — the config note tells the operator to set it to 2).
        {'dal': 1, 'rice': 1, 'bread': 2, 'salad': 2, 'dessert': 1, 'veg_dry': 1,
         'curd_side': 2, 'veg_gravy': 1, 'nonveg_main': 1, 'welcome_drink': 1}),
    'Siemens': _counter(
        'Siemens',
        ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'dessert',
         'curd_side', 'nonveg_main', 'white_rice'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'salad': 1, 'dessert': 1, 'veg_dry': 1,
         'curd_side': 1, 'veg_gravy': 1, 'nonveg_main': 2}),
    'Airtel Noida': _counter(
        'Airtel Noida',
        ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'starter', 'dal',
         'dessert', 'curd_side', 'nonveg_main'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'salad': 1, 'dessert': 1, 'starter': 1,
         'veg_dry': 1, 'curd_side': 1, 'veg_gravy': 1, 'nonveg_main': 1},
        {'friday': 'north', 'monday': 'mix', 'tuesday': 'north',
         'thursday': 'north', 'wednesday': 'mix'}),
    'Sinch NCR': _counter(
        'Sinch NCR',
        ['salad', 'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'dessert',
         'curd_side', 'nonveg_main', 'white_rice', 'welcome_drink', 'pickle'],
        {'dal': 1, 'rice': 1, 'bread': 1, 'salad': 1, 'dessert': 1, 'veg_dry': 1,
         'curd_side': 1, 'veg_gravy': 1, 'nonveg_main': 1, 'welcome_drink': 1}),
    'Junglee Games': _counter(
        'Junglee Games',
        ['bread', 'rice', 'veg_dry', 'veg_gravy', 'dessert', 'curd_side',
         'nonveg_main', 'white_rice', 'welcome_drink', 'papad', 'dal_sambar'],
        {'rice': 1, 'bread': 1, 'dessert': 1, 'veg_dry': 1, 'curd_side': 1,
         'veg_gravy': 1, 'dal_sambar': 1, 'nonveg_main': 1, 'welcome_drink': 1},
        {'friday': 'north', 'monday': 'north', 'tuesday': 'north',
         'thursday': 'south', 'wednesday': 'biryani'}),
}


@pytest.fixture(scope='module')
def _ncr_df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('NCR'))


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


def _plan(api, name):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api.app.test_client().post('/api/v1/plan', json={
        'client_name': name, 'start_date': MONDAY, 'num_days': 5,
        'time_limit_sec': TIME_LIMIT})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['solution']


def _protein(df, base):
    row = df[df['item'].astype(str).str.strip() == base]
    return None if row.empty else str(row.iloc[0]['primary_protein']).lower()


def _is_egg(df, base):
    row = df[df['item'].astype(str).str.strip() == base]
    return not row.empty and pd.to_numeric(
        row.iloc[0].get('is_egg_dish'), errors='coerce') == 1


def _nonveg_by_day(solution):
    """weekday -> list of nonveg_main item bases."""
    out = {}
    for i, day in enumerate(solution.values()):
        items = day.get('items') or {}
        out[WEEKDAYS[i]] = [c['item_base'] for s, c in items.items()
                            if s.startswith('nonveg_main')]
    return out


def _paneer_days(df, solution):
    days = 0
    for day in solution.values():
        bases = [c['item_base'] for c in (day.get('items') or {}).values()]
        if any(_protein(df, b) == 'paneer' for b in bases):
            days += 1
    return days


def _flag(df, base, col):
    row = df[df['item'].astype(str).str.strip() == base]
    return not row.empty and pd.to_numeric(
        row.iloc[0].get(col), errors='coerce') == 1


def _slot_by_day(solution, base_slot):
    """weekday -> list of item_bases for base_slot's cells that day."""
    out = {}
    for i, day in enumerate(solution.values()):
        items = day.get('items') or {}
        out[WEEKDAYS[i]] = [c['item_base'] for s, c in items.items()
                            if s.split('__')[0] == base_slot]
    return out


def _veg_gravy_by_day(solution):
    return _slot_by_day(solution, 'veg_gravy')


def test_stryker_salad_bread_rice_and_gravies(api, _ncr_df):
    sol = _plan(api, 'Stryker NCR')
    # Salad 1 = green salad every day (the pinned __1 expansion); salad 2 varies.
    salads = _slot_by_day(sol, 'salad')
    assert all('green_salad' in day for day in salads.values()), salads
    # Bread 1 = tawa roti every day.
    breads = _slot_by_day(sol, 'bread')
    assert all('tawa_roti' in day for day in breads.values()), breads
    # Rice split: flavour rice Mon/Wed/Thu/Fri, white rice (const) Tue only.
    rice = _slot_by_day(sol, 'rice')
    white = _slot_by_day(sol, 'white_rice')
    assert rice['tue'] == [] and white['tue'], (rice, white)
    for wd in ('mon', 'wed', 'thu', 'fri'):
        assert rice[wd] and white[wd] == [], (wd, rice[wd], white[wd])
    # Two paneer gravies + one kofta gravy in the week.
    vg = _veg_gravy_by_day(sol)
    flat = [b for day in vg.values() for b in day]
    assert sum(1 for b in flat if _protein(_ncr_df, b) == 'paneer') == 2, flat
    assert sum(1 for b in flat
               if _flag(_ncr_df, b, 'is_veg_kofta_gravy')) == 1, flat
    # Egg gravy once; fish at most once.
    nv = _nonveg_by_day(sol)
    assert sum(1 for v in nv.values() if any(_is_egg(_ncr_df, b) for b in v)) == 1
    assert sum(1 for v in nv.values()
               if any(_flag(_ncr_df, b, 'is_fish_dish') for b in v)) <= 1


def test_siemens_pair_paneer_soya(api, _ncr_df):
    sol = _plan(api, 'Siemens')
    # Salad green + bread plain chapati daily.
    assert all('green_salad' in d or 'green salad' in d
               for d in _slot_by_day(sol, 'salad').values())
    assert all(d for d in _slot_by_day(sol, 'bread').values())
    # Tuesday = one chicken + one egg; every other day = two chicken.
    nv = _nonveg_by_day(sol)
    for wd, bases in nv.items():
        chicken = [b for b in bases if _protein(_ncr_df, b) == 'chicken']
        eggs = [b for b in bases if _is_egg(_ncr_df, b)]
        if wd == 'tue':
            assert len(chicken) >= 1 and len(eggs) >= 1, (wd, bases)
        else:
            assert len(chicken) == 2, (wd, bases)
    # One paneer, one soya in the veg gravy.
    vg = [b for day in _veg_gravy_by_day(sol).values() for b in day]
    assert sum(1 for b in vg if _protein(_ncr_df, b) == 'paneer') == 1, vg
    assert sum(1 for b in vg
               if _protein(_ncr_df, b) in ('soya', 'soy')) == 1, vg


def test_airtel_nonveg_only_wed_and_fri(api, _ncr_df):
    sol = _plan(api, 'Airtel Noida')
    nv = _nonveg_by_day(sol)
    served = {wd for wd, bases in nv.items() if bases}
    assert served == {'wed', 'fri'}, nv


def test_sinch_chicken_mwf_egg_tue_thu(api, _ncr_df):
    sol = _plan(api, 'Sinch NCR')
    nv = _nonveg_by_day(sol)
    for wd in ('mon', 'wed', 'fri'):
        assert any(_protein(_ncr_df, b) == 'chicken' for b in nv[wd]), (wd, nv[wd])
    for wd in ('tue', 'thu'):
        assert any(_is_egg(_ncr_df, b) for b in nv[wd]), (wd, nv[wd])


def test_sinch_bread_rice_raita_welcome_by_weekday(api, _ncr_df):
    sol = _plan(api, 'Sinch NCR')
    # Bread is tawa roti every day.
    assert all(d for d in _slot_by_day(sol, 'bread').values())
    # Flavour rice Mon/Wed only; white rice (const) Tue/Thu/Fri only.
    rice = _slot_by_day(sol, 'rice')
    white = _slot_by_day(sol, 'white_rice')
    for wd in ('mon', 'wed'):
        assert rice[wd] and white[wd] == [], (wd, rice[wd], white[wd])
    for wd in ('tue', 'thu', 'fri'):
        assert rice[wd] == [] and white[wd], (wd, rice[wd], white[wd])
    # Raita (curd_side) only Mon/Fri; welcome drink only Tue/Thu.
    curd = _slot_by_day(sol, 'curd_side')
    assert curd['mon'] and curd['fri']
    assert curd['tue'] == [] and curd['wed'] == [] and curd['thu'] == []
    wd_drink = _slot_by_day(sol, 'welcome_drink')
    assert wd_drink['tue'] and wd_drink['thu']
    assert wd_drink['mon'] == [] and wd_drink['wed'] == [] and wd_drink['fri'] == []


def test_sinch_starter_wednesday_chaat_when_slot_added(monkeypatch, _ncr_df):
    """The starter rules are inert until a starter slot exists; once it does,
    the starter runs Wednesday only and must be a chaat (sub_category
    chaat_/_tikki)."""
    base = CLIENTS['Sinch NCR']
    counter = dict(base['counters'][0])
    counter['categories'] = list(counter['categories']) + ['starter']
    counter['slot_counts'] = {**counter['slot_counts'], 'starter': 1}
    seeded = {**base, 'counters': [counter]}

    import src.db as db_mod
    fake = FakeSupabase(seed={'clients': [seeded], 'app_settings': [],
                              'menu_history': [], 'week_signatures': []})
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True

    sol = _plan(api_app, 'Sinch NCR')
    starters = _slot_by_day(sol, 'starter')
    assert starters['wed'], starters  # served on Wednesday
    for wd in ('mon', 'tue', 'thu', 'fri'):
        assert starters[wd] == [], (wd, starters[wd])
    row = _ncr_df[_ncr_df['item'].astype(str).str.strip() == starters['wed'][0]]
    assert str(row.iloc[0]['sub_category']).strip() == 'chaat_/_tikki'


def test_junglee_chicken_four_days_egg_once(api, _ncr_df):
    sol = _plan(api, 'Junglee Games')
    nv = _nonveg_by_day(sol)
    chicken_days = sum(1 for v in nv.values()
                       if any(_protein(_ncr_df, b) == 'chicken' for b in v))
    egg_days = sum(1 for v in nv.values() if any(_is_egg(_ncr_df, b) for b in v))
    assert chicken_days >= 4, nv
    assert egg_days == 1, nv
    assert _paneer_days(_ncr_df, sol) == 1
