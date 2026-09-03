"""Per-city item ontology: resolution, caching and the mandatory-slot check.

The item list is per city (``data/raw/city_items/<city>.xlsx``), selected from
``clients.city`` the same way the ruleset already is. These tests pin the three
things that go wrong quietly:

* a city falling back to the wrong list (or Pune silently getting Bangalore's),
* two cities sharing the default file loading it twice (memory, not correctness),
* the mandatory-slot check either crashing on a city that legitimately does not
  serve a category, or going soft for the city that should still be held to it.
"""

import json

import pandas as pd
import pytest

from api.config import (
    CITY_ITEMS_DIR,
    DEFAULT_EXCEL_PATH,
    DEFAULT_ONTOLOGY_CITY,
    city_excel_path,
    city_required_slots,
    city_slug,
)
from src.constants import BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS
from src.preprocessor.pool_builder import PoolBuilder


class TestCityExcelPath:
    def test_pune_resolves_to_its_own_file(self):
        assert city_excel_path('Pune') == str(CITY_ITEMS_DIR / 'pune.xlsx')

    def test_default_city_resolves_to_the_default_path(self):
        assert city_excel_path(DEFAULT_ONTOLOGY_CITY) == DEFAULT_EXCEL_PATH

    # Chennai, NCR and now Hyderabad have each dropped off this list as they
    # got their own workbook — EVERY city in AVAILABLE_CITIES has one today, so
    # the only remaining fallback cases are a blank city and a name nobody has
    # added yet. `Kolkata` stands for the latter deliberately: the fallback has
    # to hold for a city the app has never heard of, which is exactly the state
    # a new city is in between "a client row names it" and "someone drops in
    # city_items/<slug>.xlsx".
    @pytest.mark.parametrize('city', [None, '', 'Kolkata'])
    def test_city_without_a_file_falls_back_to_default(self, city):
        """Adding a city to AVAILABLE_CITIES must not break planning — it keeps
        using the default list until someone drops in city_items/<slug>.xlsx."""
        assert city_excel_path(city) == DEFAULT_EXCEL_PATH

    def test_slug_normalises_case_and_spaces(self):
        assert city_slug('  New Delhi ') == 'new_delhi'
        assert city_slug(None) == ''

    def test_every_available_city_resolves_to_a_real_file(self):
        from src.client.client_config import AVAILABLE_CITIES
        import os
        for city in AVAILABLE_CITIES:
            assert os.path.isfile(city_excel_path(city)), city


class TestCityRequiredSlots:
    def test_declared_city_gets_its_declared_set(self):
        required = city_required_slots('Pune')
        assert required is not None
        # Pune serves no non-veg station and no sambar/rasam.
        assert 'nonveg_main' not in required
        assert 'veg_gravy' in required

    def test_undeclared_city_keeps_the_full_mandatory_check(self):
        """Bangalore must still fail loudly if a mapping regression empties a
        slot — that is the whole point of the check."""
        assert city_required_slots(DEFAULT_ONTOLOGY_CITY) is None
        # Hyderabad has its own workbook now but is deliberately NOT declared:
        # it was seeded from Bangalore's list, so it covers every mandatory slot
        # and the undeclared default is the STRICTER check. Declaring it would
        # only lower the bar.
        assert city_required_slots('Hyderabad') is None

    def test_manifest_only_names_real_base_slots(self):
        """A typo'd slot name in the manifest would silently drop that slot from
        the check rather than being rejected anywhere."""
        with open(CITY_ITEMS_DIR / 'ontology_categories.json', encoding='utf-8') as fh:
            raw = json.load(fh)
        for city, slots in raw.items():
            if city.startswith('_'):
                continue
            unknown = set(slots) - set(BASE_SLOT_NAMES)
            assert not unknown, f"{city} declares unknown slot(s) {sorted(unknown)}"


class TestBuildPoolsRequiredSlots:
    @staticmethod
    def _tiny_df():
        return pd.DataFrame([
            {'item': 'dal_fry', 'course_type': 'dal', 'item_color': 'yellow'},
            {'item': 'veg_kurma', 'course_type': 'veg_gravy', 'item_color': 'white'},
        ])

    def test_default_requires_every_mandatory_slot(self):
        with pytest.raises(ValueError, match="has 0 items"):
            PoolBuilder.build_pools(self._tiny_df())

    def test_declared_subset_is_the_only_thing_checked(self):
        pools = PoolBuilder.build_pools(
            self._tiny_df(), required_slots={'dal', 'veg_gravy'},
        )
        assert len(pools['dal']) == 1
        assert len(pools['nonveg_main']) == 0  # present but empty, not an error

    def test_empty_set_skips_the_check(self):
        pools = PoolBuilder.build_pools(self._tiny_df(), required_slots=set())
        assert 'dal' in pools

    def test_declared_slot_that_is_empty_still_raises(self):
        with pytest.raises(ValueError, match="'rice' has 0 items"):
            PoolBuilder.build_pools(
                self._tiny_df(), required_slots={'dal', 'rice'},
            )


class TestPuneOntologyFile:
    @pytest.fixture(scope='class')
    def pune_df(self):
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader
        return DataCleanser(ExcelReader(city_excel_path('Pune')).read()).clean()

    def test_columns_match_the_reference_ontology(self, pune_df):
        from src.preprocessor.data_cleanser import DataCleanser
        from src.preprocessor.excel_reader import ExcelReader
        ref = DataCleanser(ExcelReader(DEFAULT_EXCEL_PATH).read()).clean()
        assert set(pune_df.columns) == set(ref.columns)

    def test_every_declared_category_is_populated(self, pune_df):
        pools = PoolBuilder.build_pools(
            pune_df, required_slots=city_required_slots('Pune'),
        )
        for slot in city_required_slots('Pune'):
            assert len(pools[slot]) > 0, slot

    def test_manifest_declares_everything_the_file_covers(self, pune_df):
        """Keeps the manifest honest: a category present in the workbook but
        missing from the manifest is a slot nothing would notice losing."""
        pools = PoolBuilder.build_pools(pune_df, required_slots=set())
        covered = {
            s for s in BASE_SLOT_NAMES
            if len(pools.get(s, [])) > 0 and s not in DEFAULT_OFF_SLOTS
        }
        assert covered == set(city_required_slots('Pune'))

    def test_pool_tokens_are_common_only(self, pune_df):
        """The Pune workbook is the whole Pune universe, so its `client` column
        is `common`: a Pune client with source_pools=[] must see all of it."""
        from src.preprocessor.client_pool_filter import (
            available_pool_tokens, filter_eligible, get_active_pools,
        )
        assert available_pool_tokens(pune_df) == set()
        eligible = filter_eligible(pune_df, get_active_pools([]))
        assert len(eligible) == len(pune_df)

    def test_pune_list_carries_no_nonveg(self, pune_df):
        from src.preprocessor.pool_builder import _nonveg_mask
        assert int(_nonveg_mask(pune_df).sum()) == 0


class TestPerCityCaches:
    def test_menu_data_is_keyed_by_resolved_path(self, fake_supabase):
        """Cities sharing a workbook share ONE cache entry; a city with its own
        file gets its own.

        Every city in AVAILABLE_CITIES has its own workbook now — Chennai, then
        NCR, then Hyderabad each stopped being the example as one was added — so
        the sharing case is a city that FALLS BACK to the default list. That is
        not a hypothetical: it is the state of any city a client row names
        before someone drops in `city_items/<slug>.xlsx`, and it is the reason
        the key is the resolved path rather than the city name."""
        import api.app as api_app
        api_app.reset_caches()

        blr_df, _ = api_app._get_menu_data('Bangalore')
        fallback_df, _ = api_app._get_menu_data('Kolkata')   # no file of its own
        pune_df, _ = api_app._get_menu_data('Pune')
        hyd_df, _ = api_app._get_menu_data('Hyderabad')

        assert blr_df is fallback_df
        assert pune_df is not blr_df
        assert hyd_df is not blr_df
        assert len(pune_df) < len(blr_df)
        # Hyderabad was seeded FROM Bangalore, so it is a superset, not a subset
        # — and a separate cache entry, which is the assertion that matters.
        assert len(hyd_df) > len(blr_df)
        # bangalore (shared with the fallback city) + pune + hyderabad
        assert api_app._ontology.cache_sizes()['menu_data'] == 3

    def test_nonveg_items_are_per_city(self, fake_supabase):
        import api.app as api_app
        assert api_app._get_nonveg_items('Pune') == set()
        assert len(api_app._get_nonveg_items('Bangalore')) > 0

    def test_ontology_item_names_are_per_city(self, fake_supabase):
        """A pin naming a dish only Bangalore carries must not be handed to the
        solver as a Pune candidate — there is no pool row for it."""
        import api.app as api_app
        blr = api_app._ontology_item_names('Bangalore')
        pune = api_app._ontology_item_names('Pune')
        assert 'chicken_biryani' in blr
        assert 'chicken_biryani' not in pune
        assert 'phodnicha_bhat' in pune

    def test_filtered_cache_key_includes_the_city(self, fake_supabase):
        """The F5 pool cache used to be keyed by pool tokens alone, which would
        hand a Pune client Bangalore's `common` pool.

        Asserted on the KEY rather than by populating two entries, because
        Pune is now the only city that narrows at all — Bangalore, Chennai, NCR
        and Hyderabad are all in `FULL_POOL_CITIES` and never reach this cache.
        A count-based test would quietly stop asserting anything the next time a
        city joins that set.
        """
        import api.app as api_app
        from src.ontology.paths import city_excel_path
        api_app.reset_caches()
        api_app._get_client_loader().set_client_city('Rippling', 'Pune')
        pune_df, _ = api_app._menu_data_for_client('Rippling')
        assert len(pune_df)
        keys = list(api_app._ontology._filtered_by_path_and_pools)
        assert len(keys) == 1
        path, tokens = keys[0]
        assert path == city_excel_path('Pune')
        assert 'common' in tokens
