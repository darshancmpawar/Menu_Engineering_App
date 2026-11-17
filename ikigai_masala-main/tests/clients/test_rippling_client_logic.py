"""Rippling's client logic, against one real solve per service.

Row by row, as the requirement sheet names them: north veg dry then south veg
dry; non-veg chicken every day and an egg dish on Wednesday only; `curd`
plain curd and `curd_side` raita; bread 1 plain chapati; Sambar / Rasam one
row, rasam on the biryani day; no fruit-alone dessert; and the
make-your-own salad and dressings pinned per weekday, different for lunch and
dinner, with the salad marked non-veg on the days it carries chicken or egg.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'
# The live row as of 16 Nov 2026 (clients export): ONE counter, lunch and
# dinner as sessions of it.
RIPPLING = {
    'name': 'Rippling', 'version': 13, 'city': 'Bangalore',
    'serve_weekends': False, 'item_cooldown_days': 21, 'source_pools': [],
    'working_days': None, 'is_launch_site': False, 'shared_categories': [],
    'meals': ['lunch', 'dinner'],
    'counters': [{
        'name': 'Counter 1',
        'theme_map': {'monday': 'mix', 'tuesday': 'mix', 'wednesday': 'biryani',
                      'thursday': 'chinese', 'friday': 'north'},
        'categories': ['welcome_drink', 'soup', 'salad', 'bread', 'rice',
                       'veg_dry', 'veg_gravy', 'dal', 'dessert', 'curd',
                       'curd_side', 'nonveg_main', 'sambar_rasam', 'white_rice'],
        'slot_counts': {'dal': 1, 'curd': 1, 'rice': 1, 'soup': 1, 'bread': 2,
                        'salad': 1, 'dessert': 1, 'veg_dry': 2, 'curd_side': 1,
                        'veg_gravy': 1, 'nonveg_main': 2, 'sambar_rasam': 1,
                        'welcome_drink': 1},
    }],
}
_RULES = Path(__file__).resolve().parents[2] / 'customisation' / 'client rules' / 'rippling.json'
WEEK = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']


@pytest.fixture(scope='module')
def df():
    from src.ontology.paths import city_excel_path
    return pd.read_excel(city_excel_path('Bangalore'))


@pytest.fixture(scope='module')
def pins():
    """The pinned salad and dressing text, per session, read from the file."""
    block = json.loads(_RULES.read_text(encoding='utf-8'))['Rippling']
    return block['constant_items_by_meal']


@pytest.fixture(scope='module', params=['lunch', 'dinner'])
def plan(request):
    """`(meal, solution)` for one real /plan of that service."""
    mp = pytest.MonkeyPatch()
    import src.db as db_mod
    fake = FakeSupabase(seed={'clients': [json.loads(json.dumps(RIPPLING))],
                              'app_settings': [], 'menu_history': [],
                              'week_signatures': []})
    mp.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    mp.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    resp = api_app.app.test_client().post('/api/v1/plan', json={
        'client_name': 'Rippling', 'start_date': MONDAY, 'num_days': 5,
        'time_limit_sec': 30, 'meal': request.param})
    mp.undo()
    assert resp.status_code == 200, resp.get_json()
    return request.param, resp.get_json()['solution']


def _cells(sol, base):
    """per day: {slot_id: item_base} for one base slot."""
    return [{s: c['item_base'] for s, c in (d.get('items') or {}).items()
             if s.split('__')[0] == base} for d in sol.values()]


def _row(df, item):
    return df[df['item'].astype(str).str.strip() == item].iloc[0]


def _is(df, item, col):
    return pd.to_numeric(_row(df, item).get(col), errors='coerce') == 1


def test_north_veg_dry_first_row_south_second(plan, df):
    for day in _cells(plan[1], 'veg_dry'):
        assert str(_row(df, day['veg_dry__1']).get('cuisine_family')) == 'north_indian', day
        assert str(_row(df, day['veg_dry__2']).get('cuisine_family')) == 'south_indian', day


def test_chicken_every_day_and_egg_on_wednesday_only(plan, df):
    for wd, day in enumerate(_cells(plan[1], 'nonveg_main')):
        assert str(_row(df, day['nonveg_main__1']).get('primary_protein')) == 'chicken', day
        if wd == 2:
            assert _is(df, day['nonveg_main__2'], 'is_egg_dish'), day
        else:
            assert 'nonveg_main__2' not in day, (wd, day)


def test_curd_is_plain_and_curd_side_is_raita(plan, df):
    for day in _cells(plan[1], 'curd'):
        assert all(_is(df, i, 'is_plain_curd') for i in day.values()), day
    for day in _cells(plan[1], 'curd_side'):
        assert day and all(_is(df, i, 'is_raita') for i in day.values()), day


def test_bread_one_is_plain_chapati(plan, df):
    for day in _cells(plan[1], 'bread'):
        assert len(day) == 2
        assert _is(df, day['bread__1'], 'is_plain_phulka_chapathi'), day


def test_no_fruit_alone_dessert(plan, df):
    for day in _cells(plan[1], 'dessert'):
        for item in day.values():
            assert str(_row(df, item).get('sub_category')) != 'fresh_fruit', day


def test_sambar_rasam_is_one_row_and_rasam_on_the_biryani_day(plan, df):
    days = _cells(plan[1], 'sambar_rasam')
    assert all(len(d) == 1 for d in days), days
    kinds = [str(_row(df, next(iter(d.values()))).get('course_type')) for d in days]
    themes = [d.get('day_type') for d in plan[1].values()]
    assert 'biryani' in themes, themes
    assert kinds[themes.index('biryani')] == 'rasam', (themes, kinds)
    assert sorted(set(kinds)) == ['rasam', 'sambar'], kinds


def test_salad_and_dressing_are_the_meals_own_pins(plan, pins):
    meal, sol = plan
    mine = pins[meal]
    for wd, day in zip(WEEK, sol.values()):
        items = day['items']
        assert items['salad']['item_base'] == mine['salad'][wd]
        assert items['chutney']['item_base'] == mine['chutney'][wd]
        assert 'white_rice' in items


def test_salad_is_non_veg_exactly_when_it_carries_chicken_or_egg(plan, pins):
    meal, sol = plan
    mine = pins[meal]['salad']
    for wd, day in zip(WEEK, sol.values()):
        words = mine[wd].lower()
        expected = 'chicken' in words or 'egg' in words
        assert day['items']['salad']['is_nonveg'] is expected, (wd, mine[wd])
        assert day['items']['chutney']['is_nonveg'] is False
