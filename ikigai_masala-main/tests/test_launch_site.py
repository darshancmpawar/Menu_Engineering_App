"""The `is_launch_site` flag — config layer + API (launch view, feature F).

Every client that already exists is NON-launch (the column defaults false); a
client created through the launch view is flagged true. This pins the config
accessors and the four endpoints that read/write the flag, plus the
pre-migration degrade (missing column → everything reads false).
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")

from tests.fake_supabase import FakeSupabase


def _seed():
    return {
        'clients': [
            {'name': 'Existing Co', 'version': 1, 'city': 'Bangalore',
             'counters': [{'name': 'C1', 'categories': ['bread', 'rice'],
                           'slot_counts': {'bread': 1, 'rice': 1},
                           'theme_map': {}}]},
            {'name': 'Launch Co', 'version': 1, 'city': 'NCR',
             'is_launch_site': True,
             'counters': [{'name': 'C1', 'categories': ['bread', 'rice'],
                           'slot_counts': {'bread': 1, 'rice': 1},
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


# ------------------------------ config layer ------------------------------

class TestConfigLayer:
    def test_existing_client_is_not_a_launch_site(self, loader):
        assert loader.get_client_is_launch_site('Existing Co') is False

    def test_seeded_launch_site_reads_true(self, loader):
        assert loader.get_client_is_launch_site('Launch Co') is True

    def test_get_client_row_carries_the_flag(self, loader):
        assert loader.get_client_row('Existing Co')['is_launch_site'] is False
        assert loader.get_client_row('Launch Co')['is_launch_site'] is True

    def test_list_clients_with_city_carries_the_flag(self, loader):
        by_name = {c['name']: c for c in loader.list_clients_with_city()}
        assert by_name['Existing Co']['is_launch_site'] is False
        assert by_name['Launch Co']['is_launch_site'] is True

    def test_create_as_launch_site(self, loader):
        loader.create_client('New Site', ['bread', 'rice'], city='NCR',
                             is_launch_site=True)
        assert loader.get_client_is_launch_site('New Site') is True

    def test_create_defaults_to_non_launch(self, loader):
        loader.create_client('Plain Site', ['bread', 'rice'], city='NCR')
        assert loader.get_client_is_launch_site('Plain Site') is False

    def test_set_flag_toggles(self, loader):
        loader.set_client_is_launch_site('Existing Co', True)
        assert loader.get_client_is_launch_site('Existing Co') is True

    def test_atomic_update_carries_the_flag(self, loader):
        v = loader.get_client_version('Existing Co')
        loader.update_client_atomic('Existing Co', v, {'is_launch_site': True})
        assert loader.get_client_is_launch_site('Existing Co') is True


# ------------------------------ API layer ---------------------------------

class TestApiLayer:
    def test_clients_detail_includes_flag(self, api):
        detail = _c(api).get('/api/v1/clients').get_json()['clients_detail']
        by_name = {c['name']: c for c in detail}
        assert by_name['Existing Co']['is_launch_site'] is False
        assert by_name['Launch Co']['is_launch_site'] is True

    def test_get_config_includes_flag(self, api):
        body = _c(api).get('/api/v1/client-config/Launch Co').get_json()
        assert body['is_launch_site'] is True

    def test_create_launch_site_via_api(self, api):
        r = _c(api).post('/api/v1/client', json={
            'name': 'NCR Launch', 'city': 'NCR', 'is_launch_site': True,
            'counters': [{'name': 'C1', 'categories': ['bread', 'rice'],
                          'slot_counts': {'bread': 1, 'rice': 1},
                          'theme_map': {}}]})
        assert r.status_code == 200, r.get_json()
        got = _c(api).get('/api/v1/client-config/NCR Launch').get_json()
        assert got['is_launch_site'] is True

    def test_put_toggles_flag(self, api):
        ver = _c(api).get('/api/v1/client-config/Existing Co').get_json()['version']
        r = _c(api).put('/api/v1/client-config/Existing Co',
                        json={'version': ver, 'is_launch_site': True})
        assert r.status_code == 200, r.get_json()
        got = _c(api).get('/api/v1/client-config/Existing Co').get_json()
        assert got['is_launch_site'] is True


class TestPreMigrationDegrade:
    """A database without the column: everything reads non-launch, nothing 500s."""

    def test_missing_column_reads_false(self, monkeypatch):
        import src.db as db_mod
        # Seed rows with NO is_launch_site key at all (pre-migration shape).
        seed = _seed()
        for row in seed['clients']:
            row.pop('is_launch_site', None)
        monkeypatch.setattr(db_mod, '_sb_client', FakeSupabase(seed=seed),
                            raising=False)
        from src.client.client_config import ClientConfigLoader
        loader = ClientConfigLoader()
        assert loader.get_client_is_launch_site('Launch Co') is False
        assert all(c['is_launch_site'] is False
                   for c in loader.list_clients_with_city())
