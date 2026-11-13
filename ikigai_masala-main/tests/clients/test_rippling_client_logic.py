"""Rippling's client logic, against one real solve.

veg dry is a north + south pair; nonveg_main has a second dish on Wednesday
only (chicken + egg); `curd` serves plain curd and `curd_side` raita only;
bread__1 is plain chapati every day.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'
RIPPLING = {
    'name': 'Rippling', 'version': 5, 'city': 'Bangalore',
    'serve_weekends': False, 'item_cooldown_days': 20, 'source_pools': [],
    'working_days': None, 'is_launch_site': False,
    'counters': [{
        'name': 'Counter 1',
        'theme_map': {'monday': 'biryani', 'tuesday': 'mix', 'wednesday': 'mix',
                      'thursday': 'mix', 'friday': 'mix'},
        'categories': ['welcome_drink', 'soup', 'bread', 'rice', 'dal',
                       'sambar', 'rasam', 'veg_gravy', 'veg_dry',
                       'nonveg_main', 'curd', 'curd_side', 'dessert', 'salad'],
        'slot_counts': {'veg_dry': 2, 'bread': 2, 'nonveg_main': 2},
    }],
}


@pytest.fixture(scope='module')
def df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Bangalore'))


@pytest.fixture
def solution(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={'clients': [dict(RIPPLING)], 'app_settings': [],
                              'menu_history': [], 'week_signatures': []})
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api_app.app.test_client().post('/api/v1/plan', json={
        'client_name': 'Rippling', 'start_date': MONDAY, 'num_days': 5,
        'time_limit_sec': 30})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['solution']


def _cells(sol, base):
    """per day: {slot_id: item_base} for one base slot."""
    return [{s: c['item_base'] for s, c in (d.get('items') or {}).items()
             if s.split('__')[0] == base} for d in sol.values()]


def _row(df, item):
    return df[df['item'].astype(str).str.strip() == item].iloc[0]


def _is(df, item, col):
    return pd.to_numeric(_row(df, item).get(col), errors='coerce') == 1


def test_veg_dry_is_north_plus_south(solution, df):
    for day in _cells(solution, 'veg_dry'):
        fam = sorted(str(_row(df, i).get('cuisine_family')) for i in day.values())
        assert fam == ['north_indian', 'south_indian'], day


def test_second_nonveg_only_on_wednesday_as_chicken_and_egg(solution, df):
    for wd, day in enumerate(_cells(solution, 'nonveg_main')):
        if wd != 2:
            assert len(day) == 1, (wd, day)
            continue
        assert len(day) == 2, day
        items = list(day.values())
        assert any(str(_row(df, i).get('primary_protein')) == 'chicken'
                   for i in items), items
        assert any(_is(df, i, 'is_egg_dish') for i in items), items


def test_curd_is_plain_and_curd_side_is_raita(solution, df):
    for day in _cells(solution, 'curd'):
        assert all(_is(df, i, 'is_plain_curd') for i in day.values()), day
    for day in _cells(solution, 'curd_side'):
        assert day and all(_is(df, i, 'is_raita') for i in day.values()), day


def test_bread_one_is_plain_chapati(solution, df):
    for day in _cells(solution, 'bread'):
        assert len(day) == 2
        assert _is(df, day['bread__1'], 'is_plain_phulka_chapathi'), day
