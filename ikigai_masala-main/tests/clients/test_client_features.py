"""Add-on feature switches per client (`clients.features`, 2.08.01).

Six switches the editor sets and the planner reads: regional days, explain the
menu, ask the chef, the banned-vegetable panel, the veg / non-veg marker and
last served. Unset means off: the owner turns each on per client.
"""

import json

import pytest

from src.client.client_config import normalize_features
from src.constants import FEATURE_DEFAULTS
from tests.fake_supabase import FakeSupabase


def test_unset_reads_as_the_defaults_and_stored_values_win():
    assert not any(FEATURE_DEFAULTS.values())     # all off until switched on
    assert normalize_features(None) == FEATURE_DEFAULTS
    assert normalize_features({'veg_markers': True, 'bogus': True}) == {
        **FEATURE_DEFAULTS, 'veg_markers': True}
    assert normalize_features('garbage') == FEATURE_DEFAULTS


def test_the_editor_offers_every_switch():
    from customisation.main import FEATURE_LABELS
    assert list(FEATURE_LABELS) == list(FEATURE_DEFAULTS)


def test_switches_round_trip_through_the_api(monkeypatch):
    import src.db as db_mod
    row = {'name': 'Acme', 'version': 1, 'city': 'Bangalore',
           'counters': [{'name': 'Counter 1', 'categories': ['dal'],
                         'slot_counts': {'dal': 1}, 'theme_map': {}}]}
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed={
        'clients': [row], 'app_settings': [], 'menu_history': [],
        'week_signatures': []}), raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    c = api_app.app.test_client()
    assert c.get('/api/v1/client-config/Acme').get_json()['features'] == FEATURE_DEFAULTS
    want = {**FEATURE_DEFAULTS, 'ask_chef': False, 'last_served': True}
    resp = c.put('/api/v1/client-config/Acme', json={'version': 1, 'features': want})
    assert resp.status_code == 200, resp.get_json()
    assert c.get('/api/v1/client-config/Acme').get_json()['features'] == want
