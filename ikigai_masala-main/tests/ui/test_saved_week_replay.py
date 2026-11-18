"""A saved week is shown from history for every service, not lunch alone.

Owner, 18 Nov: Rippling's 2-13 Nov menus were in the database, yet picking
9 Nov generated a fresh plan. The page replayed history only for a lunch-only
run, so a lunch + dinner site never saw a saved week. And the saved-plan read
took the client's FIRST counter for the day themes, which at Rippling is the
breakfast counter (every day "mix")."""
from __future__ import annotations

import ast as _ast
import copy
import datetime as dt
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _app_function(name, ns):
    tree = _ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    found = [n for n in tree.body if isinstance(n, _ast.FunctionDef) and n.name == name]
    assert found, f'app.py no longer defines {name} at module level'
    exec(compile(_ast.Module(body=found, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns[name]


class _Api:
    def __init__(self, saved_meals):
        self.saved_meals, self.asked = set(saved_meals), []

    def get_saved_plan(self, *, client_name, start_date, num_days, meal):
        self.asked.append(meal)
        return {'exists': meal in self.saved_meals, 'solution': {'meal': meal}}


@pytest.fixture
def saved_weeks_by_meal():
    ns = {'flatten_result': lambda saved: {'plan': dict(saved['solution'])}, 'dt': dt}
    return _app_function('_saved_weeks_by_meal', ns)


NAMES = {'lunch': ['Counter 1'], 'dinner': ['Counter 1']}


def test_every_saved_service_is_replayed(saved_weeks_by_meal):
    got = saved_weeks_by_meal(_Api({'lunch', 'dinner'}), 'Rippling', '2026-11-09', 5,
                              ['lunch', 'dinner'], NAMES)
    assert set(got) == {'lunch', 'dinner'}
    for meal, (blk,) in got.items():
        assert blk['source'] == 'history' and blk['meal'] == meal
        assert blk['plan'] == {'meal': meal}


def test_a_service_without_its_week_means_generate_all(saved_weeks_by_meal):
    """All or nothing: a stored lunch beside a fresh dinner would skip the
    exclusions between them."""
    api = _Api({'lunch'})
    assert saved_weeks_by_meal(api, 'Rippling', '2026-11-23', 5,
                               ['lunch', 'dinner'], NAMES) == {}
    assert api.asked == ['lunch', 'dinner']


class _GapApi:
    """16-20 Nov saved except 17 Nov (deleted, owner 18 Nov)."""
    def __init__(self, missing='2026-11-17'):
        self.missing = missing

    def get_saved_plan(self, *, client_name, start_date, num_days, meal):
        days = ['2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20']
        return {'exists': False, 'covered_dates': [d for d in days if d != self.missing],
                'solution': {d: {'is_working_day': True, 'items': {}} for d in days}}


@pytest.fixture
def replay_on_18_nov():
    class _Date(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 18)
    ns = {'flatten_result': lambda saved: {'plan': dict(saved['solution'])},
          'dt': type('dt', (), {'date': _Date})}
    return _app_function('_saved_weeks_by_meal', ns)


def test_a_past_day_with_nothing_saved_stays_blank(replay_on_18_nov):
    got = replay_on_18_nov(_GapApi(), 'Rippling', '2026-11-16', 5, ['lunch', 'dinner'], NAMES)
    assert set(got) == {'lunch', 'dinner'}
    assert got['lunch'][0]['plan']['2026-11-17']['items'] == {}


def test_a_missing_day_still_to_come_means_generate(replay_on_18_nov):
    assert replay_on_18_nov(_GapApi('2026-11-19'), 'Rippling', '2026-11-16', 5,
                            ['lunch', 'dinner'], NAMES) == {}


def test_the_saved_plan_uses_the_meals_own_counter_themes(monkeypatch):
    from tests.clients.test_rippling_client_logic import RIPPLING
    from tests.fake_supabase import FakeSupabase
    import src.db as db_mod
    import api.app as api_app

    row = copy.deepcopy(RIPPLING)   # first counter: breakfast, every day 'mix'
    week = ['2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13']
    hist = [{'client_name': 'Rippling', 'service_date': d, 'meal': 'dinner',
             'menu': {'dal': 'dal_makhani'}} for d in week]
    fake = FakeSupabase(seed={'clients': [row], 'app_settings': [],
                              'week_signatures': [], 'menu_history': hist})
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    body = api_app.app.test_client().get(
        '/api/v1/saved-plan?client_name=Rippling&start_date=2026-11-09&num_days=5&meal=dinner'
    ).get_json()
    assert body['exists'] is True, json.dumps(body)[:300]
    dinner_counter = next(c for c in row['counters'] if 'dinner' in c.get('meals', []))
    want = dinner_counter['theme_map']['wednesday']   # 'biryani' in the fixture
    assert want != 'mix'
    assert body['solution']['2026-11-11']['day_type'] == want


def test_a_regional_day_is_saved_and_shown_again(monkeypatch):
    """Owner, 18 Nov: a reopened week shows its regional day in the header,
    as it did when planned, with that region's dishes marked."""
    from tests.clients.test_rippling_client_logic import RIPPLING
    from tests.fake_supabase import FakeSupabase
    import src.db as db_mod
    import api.app as api_app

    fake = FakeSupabase(seed={'clients': [copy.deepcopy(RIPPLING)], 'app_settings': [],
                              'week_signatures': [], 'menu_history': []})
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    week = ['2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13']
    api = api_app.app.test_client()
    resp = api.post('/api/v1/save', json={
        'client_name': 'Rippling', 'week_start': week[0], 'meal': 'dinner',
        'week_plan': {d: {'dal': 'bele_saru'} for d in week},
        # Spelled loosely, plus one the planner does not offer (Italian is
        # too thin to theme a day): only our own region, in our spelling.
        'regions': {week[0]: ' karnataka', week[1]: 'Italian'}})
    assert resp.status_code == 200, resp.get_json()
    stored = {r['service_date']: r.get('region')
              for r in fake.table('menu_history').select('*').execute().data}
    assert stored == {week[0]: 'Karnataka', **{d: None for d in week[1:]}}

    body = api.get('/api/v1/saved-plan?client_name=Rippling&start_date=2026-11-09'
                   '&num_days=5&meal=dinner').get_json()
    assert body['region_days'] == {week[0]: 'Karnataka'}
    assert 'bele_saru' in body['regional_dishes'][week[0]]   # a Karnataka dish


def test_a_database_without_the_column_still_saves_the_menu(monkeypatch):
    """The label is never worth the menu: saved again without `region`."""
    from src.history import history_manager as hm
    written = []

    def write(sb, rows, *a, **k):
        if any('region' in r for r in rows):
            raise Exception("Could not find the 'region' column of 'menu_history' "
                            "in the schema cache")
        written.append(rows)

    monkeypatch.setattr(hm, '_write_day_rows', write)
    hm._write_history(None, [{'service_date': '2026-11-09', 'menu': {'dal': 'x'},
                              'region': 'Karnataka'}], 'Rippling', ['2026-11-09'], 'lunch')
    assert written == [[{'service_date': '2026-11-09', 'menu': {'dal': 'x'}}]]


def test_any_other_failure_is_not_swallowed(monkeypatch):
    from src.history import history_manager as hm

    def write(sb, rows, *a, **k):
        raise Exception('connection reset')

    monkeypatch.setattr(hm, '_write_day_rows', write)
    with pytest.raises(Exception, match='connection reset'):
        hm._write_history(None, [{'service_date': 'd', 'menu': {}, 'region': 'Karnataka'}],
                          'Rippling', ['d'], 'lunch')
