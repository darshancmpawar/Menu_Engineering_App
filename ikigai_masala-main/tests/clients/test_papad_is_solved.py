"""Papad comes from the solver (owner, 18 Nov): the row was the fixed text
"Papad" every day; it is now chosen from the city's Papad category, a different
papad each day of the week (a cooldown-exempt side, like soup), and it is not
a pinned cell, so Regenerate can change it."""
from __future__ import annotations

from src.constants import (
    BASE_SLOT_NAMES, CONST_SLOTS, CONSTANT_ITEMS, COOLDOWN_EXEMPT_SLOTS,
    DEFAULT_OFF_SLOTS, EXEMPT_FROM_CUISINE,
)


def test_papad_is_a_solved_optional_row():
    assert 'papad' in BASE_SLOT_NAMES
    assert 'papad' not in CONST_SLOTS and 'papad' not in CONSTANT_ITEMS
    # Once a week's papads are used it may come back (no 21-day ban), any day's
    # theme takes any papad, and a fresh client starts without the row.
    assert 'papad' in COOLDOWN_EXEMPT_SLOTS
    assert 'papad' in EXEMPT_FROM_CUISINE
    assert 'papad' in DEFAULT_OFF_SLOTS


def test_a_bangalore_week_serves_a_different_papad_each_day(monkeypatch):
    from tests.fake_supabase import FakeSupabase
    from tests.client_fixtures import CLIENTS
    import src.db as db_mod
    import api.app as api_app
    from api.rate_limit import reset_for_tests
    from src.ontology import repository

    client = dict(next(c for c in CLIENTS if c['name'] == 'Clario'))
    fake = FakeSupabase(seed={'clients': [client], 'app_settings': [],
                              'week_signatures': [], 'menu_history': []})
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    reset_for_tests()
    resp = api_app.app.test_client().post('/api/v1/plan', json={
        'client_name': 'Clario', 'start_date': '2026-11-23', 'num_days': 5,
        'time_limit_seconds': 60, 'meal': 'lunch'})
    body = resp.get_json() or {}
    assert resp.status_code == 200, body.get('error')

    df, _ = repository.menu_data('Bangalore')
    papads = set(df.loc[df['course_type'] == 'papad', 'item'].astype(str))
    served = [day['items']['papad'] for day in body['solution'].values()
              if (day.get('items') or {}).get('papad')]
    working = [d for d in body['solution'].values() if d.get('is_working_day')]
    assert len(served) == len(working) == 4, served   # Clario: Mon-Thu
    assert {c['item_base'] for c in served} <= papads
    assert len({c['item_base'] for c in served}) == len(served), served
    assert not any(c['is_pinned'] for c in served), 'Regenerate can change it'
