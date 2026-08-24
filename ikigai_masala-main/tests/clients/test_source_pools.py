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

    These used to assert the narrowing through the plan flow — first on
    Bangalore, then on Chennai. Both cities have since joined
    `FULL_POOL_CITIES` for the same measured reason (note 15): a list whose
    rows are mostly tagged to per-site pools, against clients that mostly have
    `source_pools = []`, leaves each of them a fraction of the city's dishes.

    That leaves **no city where the plan flow narrows observably** — Pune is
    the only one outside the set and every Pune row is `common`, so its subset
    IS its full list. So the narrowing is asserted on the mechanism directly,
    which is where a regression would actually show, and the policy is asserted
    as the policy it is.
    """

    def test_the_narrowing_mechanism_still_selects_on_the_pool_column(self):
        """`filter_eligible` is what the plan flow calls once a city is outside
        `FULL_POOL_CITIES`. Asserted on a constructed frame because no shipped
        city narrows today — and a mechanism nothing exercises is exactly the
        kind that rots."""
        import pandas as pd
        from src.preprocessor.client_pool_filter import (
            filter_eligible, get_active_pools, parse_client_pools,
        )
        df = pd.DataFrame([
            {'item_id': 1, 'item': 'a', 'client': 'common'},
            {'item_id': 2, 'item': 'b', 'client': 'acme'},
            {'item_id': 3, 'item': 'c', 'client': 'acme,other'},
            {'item_id': 4, 'item': 'd', 'client': 'other'},
        ])
        active = get_active_pools(['acme'])
        out = filter_eligible(df, active)
        assert set(out['item']) == {'a', 'b', 'c'}
        for cell in out['client']:
            assert parse_client_pools(cell) & active, cell

    def test_every_city_with_per_site_pools_is_now_full_pool(self):
        """The policy, stated as an assertion. A city whose list is carved into
        per-site pools and whose clients do not name them plans from a fraction
        of its own dishes — which is what put Bangalore, NCR and now Chennai in
        this set. Pune is outside it and needs to be: every Pune row is
        `common`, so narrowing is a no-op there rather than a loss."""
        import pandas as pd
        from src.constants import FULL_POOL_CITIES
        from src.ontology.paths import CITY_ITEMS_DIR
        for city in ('bangalore', 'chennai', 'ncr'):
            assert city in FULL_POOL_CITIES, city
        assert 'pune' not in FULL_POOL_CITIES
        pune = pd.read_excel(CITY_ITEMS_DIR / 'pune.xlsx')
        tokens = {t.strip().lower()
                  for cell in pune['client'].astype(str)
                  for t in cell.split(',') if t.strip()}
        assert tokens == {'common'}, sorted(tokens)

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

    def test_common_only_when_unset(self):
        """With no pools set, a narrowing city plans from `common` alone."""
        import pandas as pd
        from src.preprocessor.client_pool_filter import (
            filter_eligible, get_active_pools, parse_client_pools,
        )
        df = pd.DataFrame([
            {'item_id': 1, 'item': 'a', 'client': 'common'},
            {'item_id': 2, 'item': 'b', 'client': 'acme'},
        ])
        out = filter_eligible(df, get_active_pools([]))
        assert set(out['item']) == {'a'}
        for cell in out['client']:
            assert 'common' in parse_client_pools(cell), cell
