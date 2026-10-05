"""A real October plan for a Bangalore site serves nothing from the red list.

Amadeus pins a green salad, whose main ingredient is lettuce, red in October.
The product decision: the pin stays (the kitchen makes it without lettuce) and
nothing else on the red list is served.
"""
import datetime as dt

import pytest

from src.ontology import repository
from src.seasonal.bans import bans_for, default_matcher

BODY = {'client_name': 'Amadeus', 'start_date': '2026-10-26', 'num_days': 5, 'time_limit_seconds': 20}


@pytest.fixture
def plan(fake_supabase, monkeypatch):
    from api.app import app
    from tests.client_fixtures import CLIENTS
    monkeypatch.setenv('SEASONAL_BANS_ENABLED', 'true')
    fake_supabase.seed('clients', [dict(next(c for c in CLIENTS if c['name'] == 'Amadeus'))])
    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.post('/api/v1/plan', json=BODY)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['solution']


def test_only_the_pinned_dish_carries_a_red_list_vegetable(plan):
    df, _ = repository.menu_data('Bangalore')
    ki = {str(i).lower(): str(k).lower() for i, k in zip(df['item'], df['key_ingredient'])}
    m = default_matcher()
    served = []
    for iso, day in plan.items():
        bans = bans_for('Bangalore', dt.date.fromisoformat(iso))
        for slot, item in day['items'].items():
            name = item['item_base']
            if m.vegetables_in(name, ki.get(name.lower()), bans.red):
                served.append((iso, slot, name))
    assert served, 'expected the pinned green salad to stay'
    assert {name for _, _, name in served} == {'green_salad'}, served
