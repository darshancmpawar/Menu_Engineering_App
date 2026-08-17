"""NCR end-to-end: the city ontology + the (Bangalore-inherited) NCR ruleset.

NCR ships its own item list (`data/raw/city_items/ncr.xlsx`, North Indian, with
non-veg and welcome drinks) and a ruleset that currently `extends` Bangalore.
This proves the wiring: `clients.city = 'NCR'` reaches the ontology and the
ruleset, and a real solve returns a menu drawn entirely from the NCR list with
non-veg correctly tagged and no blocking diagnostics.

Pools: NCR's rows are tagged to its 8 real clients and there is no `common`
pool, so per-client narrowing needs a pool decision that is deliberately still
open (pending the client config data). This test therefore draws from all 8
pools — i.e. the full NCR list — which is what validates the ontology and rules
independently of that decision.
"""

from __future__ import annotations

import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-08-03'   # Monday, ISO week 32
TIME_LIMIT = 30

ALL_POOLS = ['Stryker', 'Carelon', 'Junglee Games', 'Airtel Noida', 'Sinch',
             'Siemens', 'SAEL', 'Corning']

SLOTS = ['welcome_drink', 'soup', 'salad', 'bread', 'rice', 'veg_dry',
         'veg_gravy', 'dal', 'nonveg_main', 'curd_side', 'dessert']

REFERENCE_NCR = {
    'name': 'NCR Reference Counter',
    'version': 1,
    'city': 'NCR',
    'serve_weekends': False,
    'item_cooldown_days': 20,
    'source_pools': ALL_POOLS,
    'counters': [{
        'name': 'Counter 1',
        'theme_map': {'monday': 'mix', 'tuesday': 'chinese',
                      'wednesday': 'biryani', 'thursday': 'south',
                      'friday': 'north'},
        'categories': SLOTS,
        'slot_counts': {s: 1 for s in SLOTS},
    }],
}


@pytest.fixture
def ncr_client(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(REFERENCE_NCR)],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    })
    monkeypatch.setattr(db_mod, '_sb_client', fake, raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _post(api_app, path, body):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api_app.app.test_client().post(path, json=body)


def _ncr_item_names():
    import pandas as pd
    from src.ontology.paths import city_excel_path
    df = pd.read_excel(city_excel_path('NCR'))
    return {str(n).strip() for n in df['item']}


def test_diagnose_is_clean(ncr_client):
    resp = _post(ncr_client, '/api/v1/diagnose', {
        'client_name': 'NCR Reference Counter',
        'start_date': MONDAY, 'num_days': 5})
    body = resp.get_json()
    assert resp.status_code == 200, body
    errors = [r for r in body.get('rule_diagnostics', [])
              if r.get('severity') == 'ERROR']
    assert not errors, errors
    assert body['summary']['would_succeed'] is True


def test_plan_generates_from_the_ncr_list(ncr_client):
    resp = _post(ncr_client, '/api/v1/plan', {
        'client_name': 'NCR Reference Counter',
        'start_date': MONDAY, 'num_days': 5, 'time_limit_sec': TIME_LIMIT})
    body = resp.get_json()
    assert resp.status_code == 200, body
    solution = body['solution']
    ncr_names = _ncr_item_names()

    day_count = 0
    for date, day in solution.items():
        items = day.get('items') or {}
        assert items, (date, 'no items')
        day_count += 1
        for slot, cell in items.items():
            base = cell['item_base']
            assert base in ncr_names, (date, slot, base)
    assert day_count == 5


def test_nonveg_is_tagged(ncr_client):
    """NCR has non-veg; a nonveg_main dish must come back flagged so the UI can
    render it red (Pune, all-veg, never does)."""
    resp = _post(ncr_client, '/api/v1/plan', {
        'client_name': 'NCR Reference Counter',
        'start_date': MONDAY, 'num_days': 5, 'time_limit_sec': TIME_LIMIT})
    solution = resp.get_json()['solution']
    nonveg_seen = [
        day['items']['nonveg_main']['is_nonveg']
        for day in solution.values()
        if 'nonveg_main' in (day.get('items') or {})
    ]
    assert nonveg_seen and all(nonveg_seen), nonveg_seen
