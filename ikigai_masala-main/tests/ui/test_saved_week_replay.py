"""A saved week is shown from history for every service, not lunch alone.

Owner, 18 Nov: Rippling's 2-13 Nov menus were in the database, yet picking
9 Nov generated a fresh plan. The page replayed history only for a lunch-only
run, so a lunch + dinner site never saw a saved week. And the saved-plan read
took the client's FIRST counter for the day themes, which at Rippling is the
breakfast counter (every day "mix")."""
from __future__ import annotations

import ast as _ast
import copy
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
    ns = {'flatten_result': lambda saved: {'plan': dict(saved['solution'])}}
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
