"""Counters are counted per SERVICE (owner report, 17 Nov).

A one-counter site whose services differ is saved as one copy of the counter
per service (`meals` tags). The planner listed all three copies for every
service, so Rippling showed "Counters 3" and planned breakfast three times; the
API called it multi-counter, which also picks the per-counter history shape.
"""

import ast
import json
from pathlib import Path

import pytest

from src.client.client_config import counter_serves
from src.history import MEALS
from tests.fake_supabase import FakeSupabase

ROOT = Path(__file__).resolve().parents[2]


def _counter(name, meals=None):
    c = {'name': name, 'categories': ['dal'], 'slot_counts': {'dal': 1},
         'theme_map': {}}
    return dict(c, meals=meals) if meals else c


ONE_COUNTER_THREE_SERVICES = [_counter('Counter 1', ['breakfast']),
                              _counter('Counter 1', ['lunch']),
                              _counter('Counter 1', ['dinner'])]
TWO_LUNCH_COUNTERS = [_counter('North', ['lunch']), _counter('South', ['lunch']),
                      _counter('Dinner', ['dinner'])]


def _names_fn():
    tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == '_client_counter_names']
    assert found, 'app.py no longer defines _client_counter_names'
    ns = {'counter_serves': counter_serves, 'MEALS': MEALS}
    exec(compile(ast.Module(body=found, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns['_client_counter_names']


class _Api:
    def __init__(self, counters):
        self.counters = counters

    def get_client_config(self, name):
        return {'counters': self.counters}


def test_the_planner_lists_each_services_own_counters():
    by_meal = _names_fn()(_Api(ONE_COUNTER_THREE_SERVICES), 'Rippling')[1]
    assert by_meal['breakfast'] == by_meal['lunch'] == ['Counter 1']
    by_meal = _names_fn()(_Api(TWO_LUNCH_COUNTERS), 'X')[1]
    assert by_meal['lunch'] == ['North', 'South'] and by_meal['dinner'] == ['Dinner']


@pytest.mark.parametrize('counters, meals, mode', [
    (ONE_COUNTER_THREE_SERVICES, ['breakfast', 'lunch', 'dinner'], 'single'),
    (TWO_LUNCH_COUNTERS, ['lunch', 'dinner'], 'multi'),
    ([_counter('A'), _counter('B')], ['lunch', 'dinner'], 'multi'),
])
def test_the_api_calls_a_client_multi_only_with_two_counters_in_a_service(
        monkeypatch, counters, meals, mode):
    import src.db as db_mod
    row = {'name': 'Acme', 'version': 1, 'city': 'Bangalore', 'meals': meals,
           'counters': json.loads(json.dumps(counters))}
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed={
        'clients': [row], 'app_settings': [], 'menu_history': [],
        'week_signatures': []}), raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    got = api_app.app.test_client().get('/api/v1/client-config/Acme').get_json()
    assert got['counter_mode'] == mode
