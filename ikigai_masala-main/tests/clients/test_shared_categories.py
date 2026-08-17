"""DB-backed `shared_categories` (the editor's cross-counter toggle+multiselect).

The base slots a client serves identically across counters are stored on
``clients.shared_categories`` and edited via the API. A client configured only
in ``client_rules.json`` (e.g. DXC) has none in the DB, so GET falls back to the
file value — the planner consumes whichever wins.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")

from tests.fake_supabase import FakeSupabase


def _seed():
    return {
        'clients': [
            {'name': 'MultiCo', 'version': 1, 'city': 'Bangalore',
             'counters': [
                 {'name': 'Veg', 'categories': ['bread', 'rice', 'veg_gravy'],
                  'slot_counts': {'bread': 1, 'rice': 1, 'veg_gravy': 1},
                  'theme_map': {}},
                 {'name': 'NonVeg', 'categories': ['bread', 'rice', 'nonveg_main'],
                  'slot_counts': {'bread': 1, 'rice': 1, 'nonveg_main': 1},
                  'theme_map': {}}]},
        ],
        'app_settings': [], 'menu_history': [], 'week_signatures': [],
    }


@pytest.fixture
def loader(monkeypatch):
    import src.db as db_mod
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed=_seed()),
                        raising=False)
    from src.client.client_config import ClientConfigLoader
    return ClientConfigLoader()


@pytest.fixture
def api(monkeypatch):
    import src.db as db_mod
    monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed=_seed()),
                        raising=False)
    import api.app as api_app
    monkeypatch.setattr(api_app, '_client_loader', None, raising=False)
    api_app.reset_caches()
    api_app.app.config['TESTING'] = True
    return api_app


def _c(api):
    from api.rate_limit import reset_for_tests
    reset_for_tests()
    return api.app.test_client()


# --- config layer ----------------------------------------------------------

class TestConfigLayer:
    def test_unset_reads_empty(self, loader):
        assert loader.get_client_shared_categories('MultiCo') == []

    def test_set_normalises_and_dedupes(self, loader):
        loader.set_client_shared_categories(
            'MultiCo', ['bread', 'rice', 'bogus_slot', 'BREAD'])
        assert loader.get_client_shared_categories('MultiCo') == ['bread', 'rice']

    def test_get_client_row_carries_it(self, loader):
        loader.set_client_shared_categories('MultiCo', ['rice'])
        assert loader.get_client_row('MultiCo')['shared_categories'] == ['rice']

    def test_create_with_shared_categories(self, loader):
        loader.create_client(
            'NewCo', counter_mode='multi',
            counters=[
                {'name': 'A', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                {'name': 'B', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}}],
            shared_categories=['bread', 'nope'])
        assert loader.get_client_shared_categories('NewCo') == ['bread']

    def test_atomic_update_carries_it(self, loader):
        v = loader.get_client_row('MultiCo')['version']
        loader.update_client_atomic(
            'MultiCo', v, {'shared_categories': ['bread', 'rice']})
        assert loader.get_client_shared_categories('MultiCo') == ['bread', 'rice']


# --- API -------------------------------------------------------------------

class TestApi:
    def test_get_exposes_it(self, api):
        body = _c(api).get('/api/v1/client-config/MultiCo').get_json()
        assert body['shared_categories'] == []

    def test_put_sets_it(self, api):
        ver = _c(api).get('/api/v1/client-config/MultiCo').get_json()['version']
        r = _c(api).put('/api/v1/client-config/MultiCo',
                        json={'version': ver, 'shared_categories': ['bread', 'x']})
        assert r.status_code == 200
        got = _c(api).get('/api/v1/client-config/MultiCo').get_json()
        assert got['shared_categories'] == ['bread']

    def test_post_creates_with_it(self, api):
        r = _c(api).post('/api/v1/client', json={
            'name': 'PostCo', 'city': 'Bangalore', 'counter_mode': 'multi',
            'counters': [
                {'name': 'A', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                {'name': 'B', 'categories': ['bread', 'rice'],
                 'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}}],
            'shared_categories': ['rice']})
        assert r.status_code == 200, r.get_json()
        got = _c(api).get('/api/v1/client-config/PostCo').get_json()
        assert got['shared_categories'] == ['rice']

    def test_falls_back_to_file_when_db_empty(self, api):
        # DXC has no DB shared_categories here, but client_rules.json does — the
        # endpoint must surface the file value so the planner still syncs.
        import src.db as db_mod
        # seed DXC as a bare client so the DB value is empty.
        db_mod._sb_client.seed('clients', [{
            'name': 'DXC', 'version': 1, 'city': 'Bangalore',
            'counters': [{'name': 'Veg Lunch', 'categories': ['bread', 'rice'],
                          'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}},
                         {'name': 'Non Veg Lunch', 'categories': ['bread', 'rice'],
                          'slot_counts': {'bread': 1, 'rice': 1}, 'theme_map': {}}]}])
        body = _c(api).get('/api/v1/client-config/DXC').get_json()
        assert 'bread' in body['shared_categories']
        assert 'rice' in body['shared_categories']
