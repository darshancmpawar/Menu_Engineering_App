"""Integration tests for F5 client-pool configuration (source_pools):
config accessors, the API surface, and the plan-flow pool filter.
"""

import pytest

flask = pytest.importorskip("flask", reason="Flask not installed")
from api.app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


class TestSourcePoolAccessors:
    def test_unset_returns_empty_list(self, fake_supabase):
        from src.client.client_config import ClientConfigLoader
        # Seeded 'Rippling' has no source_pools key -> column present, unset.
        assert ClientConfigLoader().get_client_source_pools('Rippling') == []

    def test_set_then_get_roundtrips_normalized(self, fake_supabase):
        from src.client.client_config import ClientConfigLoader
        loader = ClientConfigLoader()
        loader.set_client_source_pools('Rippling', ['Infineon', ' Healthineers '])
        assert loader.get_client_source_pools('Rippling') == ['healthineers', 'infineon']

    def test_common_is_stripped_and_deduped(self, fake_supabase):
        from src.client.client_config import ClientConfigLoader
        loader = ClientConfigLoader()
        loader.set_client_source_pools('Rippling', ['common', 'Infineon', 'infineon'])
        assert loader.get_client_source_pools('Rippling') == ['infineon']  # no 'common'


class TestSourcePoolAPI:
    def test_editor_metadata_lists_available_pools(self, client, fake_supabase):
        resp = client.get('/api/v1/editor-metadata')
        assert resp.status_code == 200
        pools = resp.get_json()['available_client_pools']
        assert isinstance(pools, list) and pools
        assert 'common' not in pools            # common is implicit
        assert all(p == p.casefold() for p in pools)  # normalized

    def test_get_config_includes_source_pools(self, client, fake_supabase):
        resp = client.get('/api/v1/client-config/Rippling')
        assert resp.status_code == 200
        assert 'source_pools' in resp.get_json()

    def test_put_rejects_unknown_pool(self, client, fake_supabase):
        ver = client.get('/api/v1/client-config/Rippling').get_json()['version']
        resp = client.put('/api/v1/client-config/Rippling', json={
            'version': ver, 'source_pools': ['not_a_real_client'],
        })
        assert resp.status_code == 400
        assert 'Unknown client pool' in resp.get_json()['error']

    def test_put_accepts_valid_pools_and_get_reflects(self, client, fake_supabase):
        # Discover a real token for Rippling's city (Bangalore). The unscoped
        # endpoint returns the cross-city union, which now includes NCR's tokens
        # — invalid for a Bangalore client — so scope it to the client's city.
        pools = client.get(
            '/api/v1/editor-metadata?city=Bangalore'
        ).get_json()['available_client_pools']
        token = pools[0]
        ver = client.get('/api/v1/client-config/Rippling').get_json()['version']
        resp = client.put('/api/v1/client-config/Rippling', json={
            'version': ver, 'source_pools': [token],
        })
        assert resp.status_code == 200
        got = client.get('/api/v1/client-config/Rippling').get_json()['source_pools']
        assert got == [token]


class TestNoCommonCityFallback:
    """A city whose list has no `common` pool (NCR — every row is tagged to a
    real client). The F5 filter must not leave such a client with an empty menu.
    """

    def _repo(self):
        from src.ontology.repository import OntologyRepository
        return OntologyRepository()

    def test_empty_pools_fall_back_to_the_full_list(self):
        repo = self._repo()
        full_df, _ = repo.menu_data('NCR')
        fdf, fpools = repo.filtered_menu_data('NCR', [])   # [] -> common-only
        # NCR has no `common`, so common-only is empty -> fall back to full.
        assert len(fdf) == len(full_df)
        assert len(fpools['bread']) > 0

    def test_common_city_still_narrows_to_common_only(self):
        """The fallback must be scoped to the empty case: a city WITH a common
        pool (Bangalore) keeps common-only narrowing, unchanged."""
        repo = self._repo()
        full_df, _ = repo.menu_data('Bangalore')
        bdf, _ = repo.filtered_menu_data('Bangalore', [])
        assert 0 < len(bdf) < len(full_df)

    def test_token_pool_builds_even_when_it_misses_a_declared_slot(self):
        """`sael` runs no nonveg_main; before, build_pools raised on the city's
        declared nonveg_main applied to the subset. Now the subset builds and
        the unserved slot is simply absent — surfaced per-counter, not a 500."""
        repo = self._repo()
        fdf, pools = repo.filtered_menu_data('NCR', ['sael'])
        assert len(fdf) > 0
        assert len(pools['bread']) > 0 and len(pools['veg_gravy']) > 0


class TestPoolPreview:
    def test_preview_counts(self, client, fake_supabase):
        # Scope to Bangalore: the unscoped union now carries NCR tokens, which
        # match nothing in the default (Bangalore) ontology the preview counts.
        pools = client.get(
            '/api/v1/editor-metadata?city=Bangalore'
        ).get_json()['available_client_pools']
        resp = client.post('/api/v1/pool-preview', json={'source_pools': [pools[0]]})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['eligible_item_count'] > 0
        assert 'common' in body['active_pools']
        assert body['category_counts']

    def test_preview_common_only(self, client, fake_supabase):
        resp = client.post('/api/v1/pool-preview', json={'source_pools': []})
        assert resp.status_code == 200
        assert resp.get_json()['active_pools'] == ['common']

    def test_preview_rejects_unknown(self, client, fake_supabase):
        resp = client.post('/api/v1/pool-preview', json={'source_pools': ['nope']})
        assert resp.status_code == 400


class TestPlanFlowFilter:
    def test_menu_data_filtered_to_active_pools(self, fake_supabase):
        import api.app as api_app
        from src.client.client_config import ClientConfigLoader
        from src.preprocessor.client_pool_filter import (
            parse_client_pools, get_active_pools,
        )
        ClientConfigLoader().set_client_source_pools('Rippling', ['infineon'])
        api_app.reset_caches()
        df, pools = api_app._menu_data_for_client('Rippling')
        active = get_active_pools(['infineon'])
        # every row in the filtered df must be eligible for common ∪ infineon
        for cell in df['client']:
            assert parse_client_pools(cell) & active, cell
        # and it must be a strict subset of the full ontology
        full_df, _ = api_app._get_menu_data()
        assert len(df) < len(full_df)

    def test_common_only_when_unset(self, fake_supabase):
        import api.app as api_app
        from src.preprocessor.client_pool_filter import parse_client_pools
        api_app.reset_caches()
        # Rippling unset -> [] -> common-only
        df, pools = api_app._menu_data_for_client('Rippling')
        for cell in df['client']:
            assert 'common' in parse_client_pools(cell), cell
