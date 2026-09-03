"""Hyderabad end-to-end: the new city list reaches a real solve.

`tests/cities/test_hyderabad_ontology.py` checks the workbook. This checks the
wiring — that `clients.city = 'Hyderabad'` resolves to `hyderabad.xlsx` and the
Bangalore-inherited ruleset, and that a solve comes back drawn from that list.

The pool assertion is the one worth having. Hyderabad is in `FULL_POOL_CITIES`
because its inherited rows carry BANGALORE client tokens — `healthineers`,
`citrix`, `booking.com` — which name sites in another city that no Hyderabad
client will ever select. Without that switch a client resolves to `common`
alone: 960 rows of 6,260, and none of Quest's 101 additions, every one of which
is tagged `quest`. So the test asserts a client with `source_pools = []` (which
is what a freshly created client has) can still reach a Quest dish. Asserted by
COUNT rather than by naming a dish, because which dish the solver picks is the
objective's business.
"""

from __future__ import annotations

import pytest

from tests.fake_supabase import FakeSupabase

MONDAY = '2026-09-07'   # Monday, ISO week 37
TIME_LIMIT = 30

SLOTS = ['welcome_drink', 'salad', 'bread', 'rice', 'veg_dry', 'veg_gravy',
         'dal', 'nonveg_main', 'curd_side', 'dessert', 'starter']

QUEST_HYD = {
    'name': 'Quest HYD Reference',
    'version': 1,
    'city': 'Hyderabad',
    'serve_weekends': False,
    'item_cooldown_days': 20,
    # Exactly what a client created through the editor starts with — and the
    # state in which the pool switch matters.
    'source_pools': [],
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
def hyd_client(monkeypatch):
    import src.db as db_mod
    fake = FakeSupabase(seed={
        'clients': [dict(QUEST_HYD)],
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


def _names(city):
    import pandas as pd
    from src.ontology.paths import city_excel_path
    df = pd.read_excel(city_excel_path(city))
    return {str(n).strip() for n in df['item']}


def test_diagnose_is_clean(hyd_client):
    resp = _post(hyd_client, '/api/v1/diagnose', {
        'client_name': 'Quest HYD Reference',
        'start_date': MONDAY, 'num_days': 5})
    body = resp.get_json()
    assert resp.status_code == 200, body
    errors = [r for r in body.get('rule_diagnostics', [])
              if r.get('severity') == 'ERROR']
    assert not errors, errors
    assert body['summary']['would_succeed'] is True


def test_plan_generates_from_the_hyderabad_list(hyd_client):
    resp = _post(hyd_client, '/api/v1/plan', {
        'client_name': 'Quest HYD Reference',
        'start_date': MONDAY, 'num_days': 5, 'time_limit_sec': TIME_LIMIT})
    body = resp.get_json()
    assert resp.status_code == 200, body
    solution = body['solution']
    hyd = _names('Hyderabad')

    day_count = 0
    for date, day in solution.items():
        items = day.get('items') or {}
        assert items, (date, 'no items')
        day_count += 1
        for slot, cell in items.items():
            assert cell['item_base'] in hyd, (date, slot, cell['item_base'])
    assert day_count == 5


def test_an_unpooled_client_still_sees_the_whole_list(hyd_client):
    """`source_pools = []` means "common only" everywhere except a
    `FULL_POOL_CITIES` city. Hyderabad's `common` is 960 of 6,260 rows and holds
    none of Quest's dishes, so this is the assertion that the switch is on."""
    import api.app as api_app
    whole, _ = api_app._ontology.menu_data('Hyderabad')
    got, _ = api_app._menu_data_for_client('Quest HYD Reference')
    assert len(got) == len(whole)


def test_quest_dishes_are_reachable(hyd_client):
    """The payoff, stated as what the client can actually be served: every one
    of the import's 101 rows is tagged `quest`, so under common-only narrowing
    none of them exists for this client."""
    import api.app as api_app
    got, _ = api_app._menu_data_for_client('Quest HYD Reference')
    tagged = got['client'].fillna('').astype(str).str.lower().str.contains('quest')
    assert int(tagged.sum()) >= 100


def test_nonveg_is_tagged(hyd_client):
    """Hyderabad has non-veg (Pune, all-veg, never does), so a nonveg_main dish
    must come back flagged for the UI to render it red."""
    resp = _post(hyd_client, '/api/v1/plan', {
        'client_name': 'Quest HYD Reference',
        'start_date': MONDAY, 'num_days': 5, 'time_limit_sec': TIME_LIMIT})
    solution = resp.get_json()['solution']
    seen = [day['items']['nonveg_main']['is_nonveg']
            for day in solution.values()
            if 'nonveg_main' in (day.get('items') or {})]
    assert seen and all(seen), seen


def test_the_ruleset_is_bangalore_s(hyd_client):
    """`hyderabad.json` is a bare `extends: bangalore` stub — the ontology is
    Hyderabad's own, the rules are not (yet). Pinned so that stops being true
    deliberately rather than by accident."""
    from src.menu_rules.menu_rule_loader import MenuRuleLoader
    loader = MenuRuleLoader()
    hyd = {r.name for r in loader.load_for_city('Hyderabad')}
    blr = {r.name for r in loader.load_for_city('Bangalore')}
    assert hyd == blr
