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

    def test_common_city_still_narrows_to_common_only(self, monkeypatch):
        """The common-only narrowing still works and is gated ONLY by the
        FULL_POOL_CITIES switch — flip Bangalore out of it and the old behaviour
        is back, unchanged.

        It has to be demonstrated this way: Bangalore was the only city with a
        mixed `client` column, and it is now full-pool by choice. Chennai and
        Pune are 100% `common`, so narrowing there is a no-op and would prove
        nothing.
        """
        import src.constants as consts
        monkeypatch.setattr(consts, 'FULL_POOL_CITIES', set(), raising=True)
        repo = self._repo()
        full_df, _ = repo.menu_data('Bangalore')
        bdf, _ = repo.filtered_menu_data('Bangalore', [])
        assert 0 < len(bdf) < len(full_df), (
            'common-only narrowing should return a strict subset once the '
            'full-pool switch is off')

    def test_full_pool_city_ignores_the_narrowing(self):
        """Bangalore plans from the whole city list whatever `source_pools` says
        — an empty list, a token, anything. Removing it from FULL_POOL_CITIES
        restores per-client pools."""
        from src.constants import FULL_POOL_CITIES
        assert 'bangalore' in FULL_POOL_CITIES
        repo = self._repo()
        full_df, _ = repo.menu_data('Bangalore')
        for pools in ([], ['cloudera'], ['icon', 'infineon']):
            df, _ = repo.filtered_menu_data('Bangalore', pools)
            assert len(df) == len(full_df), (
                f'Bangalore with source_pools={pools} should be the full list')

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
    """Pool narrowing, and the cities where it is switched off.

    These two used to assert the narrowing on **Rippling**, a Bangalore client.
    Bangalore was later added to `FULL_POOL_CITIES` (note 15) precisely so its
    clients plan from the whole city list — only 893 of its 4,349 rows carry
    `common`, and most clients have `source_pools = []`, so narrowing left them
    a fifth of the list. The tests kept asserting the old behaviour. They now
    check both halves: a narrowing city narrows, a full-pool city does not.
    """

    #: The seeded client has no city, which resolves to Bangalore's workbook and
    #: therefore to the full-pool policy. Moving it to Chennai — a city that
    #: still narrows, and the one whose list carries real per-site tokens since
    #: the menu bank import — is what makes the narrowing observable at all.
    NARROWING_CITY = 'Chennai'
    NARROWING_POOL = 'tata communications'

    def _narrowing(self, loader):
        loader.set_client_city('Rippling', self.NARROWING_CITY)
        return 'Rippling'

    def test_menu_data_filtered_to_active_pools(self, fake_supabase):
        import api.app as api_app
        from src.client.client_config import ClientConfigLoader
        from src.preprocessor.client_pool_filter import (
            parse_client_pools, get_active_pools,
        )
        loader = ClientConfigLoader()
        name = self._narrowing(loader)
        loader.set_client_source_pools(name, [self.NARROWING_POOL])
        api_app.reset_caches()
        df, _ = api_app._menu_data_for_client(name)
        active = get_active_pools([self.NARROWING_POOL])
        for cell in df['client']:
            assert parse_client_pools(cell) & active, cell
        full_df, _ = api_app._get_menu_data(self.NARROWING_CITY)
        assert len(df) < len(full_df)

    def test_a_full_pool_city_ignores_source_pools(self, fake_supabase):
        """Bangalore is in `FULL_POOL_CITIES`, so naming a pool changes nothing
        — that is the point of the switch, and it is a city-level policy rather
        than anything written on the client row."""
        import api.app as api_app
        from src.client.client_config import ClientConfigLoader
        from src.constants import FULL_POOL_CITIES
        assert 'bangalore' in FULL_POOL_CITIES
        ClientConfigLoader().set_client_source_pools('Rippling', ['infineon'])
        api_app.reset_caches()
        df, _ = api_app._menu_data_for_client('Rippling')
        full_df, _ = api_app._get_menu_data()
        assert len(df) == len(full_df)

    def test_common_only_when_unset(self, fake_supabase):
        """With no pools set, a NARROWING city plans from `common` alone."""
        import api.app as api_app
        from src.client.client_config import ClientConfigLoader
        from src.preprocessor.client_pool_filter import parse_client_pools
        loader = ClientConfigLoader()
        name = self._narrowing(loader)
        loader.set_client_source_pools(name, [])
        api_app.reset_caches()
        df, _ = api_app._menu_data_for_client(name)
        for cell in df['client']:
            assert 'common' in parse_client_pools(cell), cell
