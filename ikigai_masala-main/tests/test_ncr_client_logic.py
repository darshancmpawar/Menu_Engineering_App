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
        {'dal': 1, 'rice': 1, 'bread': 1, 'salad': 2, 'dessert': 1, 'veg_dry': 1,
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


def test_stryker_paneer_twice_and_egg_once(api, _ncr_df):
    sol = _plan(api, 'Stryker NCR')
    assert _paneer_days(_ncr_df, sol) == 2
    nv = _nonveg_by_day(sol)
    egg_days = sum(1 for v in nv.values() if any(_is_egg(_ncr_df, b) for b in v))
    assert egg_days == 1


def test_siemens_two_chicken_every_day(api, _ncr_df):
    sol = _plan(api, 'Siemens')
    nv = _nonveg_by_day(sol)
    for wd, bases in nv.items():
        chicken = [b for b in bases if _protein(_ncr_df, b) == 'chicken']
        assert len(chicken) == 2, (wd, bases)
    assert _paneer_days(_ncr_df, sol) == 2


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


def test_junglee_chicken_four_days_egg_once(api, _ncr_df):
    sol = _plan(api, 'Junglee Games')
    nv = _nonveg_by_day(sol)
    chicken_days = sum(1 for v in nv.values()
                       if any(_protein(_ncr_df, b) == 'chicken' for b in v))
    egg_days = sum(1 for v in nv.values() if any(_is_egg(_ncr_df, b) for b in v))
    assert chicken_days >= 4, nv
    assert egg_days == 1, nv
    assert _paneer_days(_ncr_df, sol) == 1
