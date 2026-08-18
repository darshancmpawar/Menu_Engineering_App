"""Tests for ClientConfigLoader (consolidated clients.counters model)."""

import pytest
from unittest.mock import patch

from tests.fake_supabase import FakeSupabase
from src.client.client_config import (
    ClientConfigLoader,
    normalize_counter,
    normalize_city,
    default_counter,
    _dedupe_preserve_order,
    DEFAULT_THEME_MAP,
    MAX_COUNTERS,
    _MAX_SLOT_COUNT,
)


def _counter(name, categories, slot_counts=None, theme_map=None):
    return {
        'name': name,
        'categories': list(categories),
        'slot_counts': slot_counts or {},
        'theme_map': theme_map or {},
    }


def _make_loader(seed):
    fake = FakeSupabase(seed=seed)
    with patch('src.client.client_config.get_supabase', return_value=fake):
        return ClientConfigLoader(), fake


CATS = ['bread', 'veg_dry', 'rice', 'veg_gravy', 'dal', 'curd_side', 'dessert', 'starter']


@pytest.fixture
def loader():
    seed = {
        'clients': [
            {'name': 'Acme', 'version': 1, 'counters': [
                _counter('Counter 1', CATS, {'veg_dry': 2}, {'monday': 'north'}),
            ]},
            {'name': 'Bistro', 'version': 3, 'counters': [
                _counter('North', ['bread', 'veg_gravy', 'rice']),
                _counter('Chinese', ['starter', 'veg_dry'], {'veg_dry': 3}),
            ]},
        ],
        'app_settings': [],
    }
    return _make_loader(seed)


class TestReads:
    def test_client_names_sorted(self, loader):
        ld, _ = loader
        assert ld.client_names == ['Acme', 'Bistro']

    def test_get_client_expands_frequency(self, loader):
        ld, _ = loader
        cfg = ld.get_client('Acme')
        # veg_dry x2 → expanded slots
        assert 'veg_dry__1' in cfg.active_slots
        assert 'veg_dry__2' in cfg.active_slots
        assert 'veg_dry' not in cfg.active_slots
        assert cfg.slot_counts['veg_dry'] == 2
        assert cfg.theme_map['monday'] == 'north'

    def test_get_client_single_count_not_expanded(self, loader):
        ld, _ = loader
        cfg = ld.get_client('Bistro')  # primary = North, no overrides
        assert 'bread' in cfg.active_slots
        assert 'veg_gravy' in cfg.active_slots

    def test_get_counters_for_client(self, loader):
        ld, _ = loader
        counters = ld.get_counters_for_client('Bistro')
        assert [c['name'] for c in counters] == ['North', 'Chinese']
        assert counters[1]['slot_counts']['veg_dry'] == 3

    def test_counter_mode_single_vs_multi(self, loader):
        ld, _ = loader
        assert ld.get_counter_mode('Acme') == 'single'
        assert ld.get_counter_mode('Bistro') == 'multi'

    def test_get_counter_setup(self, loader):
        ld, _ = loader
        mode, counters = ld.get_counter_setup('Bistro')
        assert mode == 'multi'
        assert len(counters) == 2

    def test_unknown_client_raises(self, loader):
        ld, _ = loader
        with pytest.raises(ValueError, match="Unknown client"):
            ld.get_client('Nope')

    def test_get_client_version(self, loader):
        ld, _ = loader
        assert ld.get_client_version('Bistro') == 3


class TestWrites:
    def test_create_client_classic(self):
        ld, fake = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('New', ['rice', 'dal', 'veg_dry'])
        row = [r for r in fake.rows('clients') if r['name'] == 'New'][0]
        assert len(row['counters']) == 1
        assert set(row['counters'][0]['categories']) == {'rice', 'dal', 'veg_dry'}
        assert ld.get_counter_mode('New') == 'single'

    def test_create_client_multi(self):
        ld, fake = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Multi', counter_mode='multi', counters=[
            _counter('A', ['rice']), _counter('B', ['dal']),
        ])
        row = [r for r in fake.rows('clients') if r['name'] == 'Multi'][0]
        assert [c['name'] for c in row['counters']] == ['A', 'B']

    def test_create_rejects_empty_categories(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        with pytest.raises(ValueError, match="category"):
            ld.create_client('Bad', counter_mode='multi', counters=[
                _counter('Empty', []),
            ])

    def test_set_counters_single_truncates(self, loader):
        ld, fake = loader
        ld.set_counters_for_client('Bistro', 'single', [
            _counter('Keep', ['rice']), _counter('Drop', ['dal']),
        ])
        row = [r for r in fake.rows('clients') if r['name'] == 'Bistro'][0]
        assert len(row['counters']) == 1
        assert row['counters'][0]['categories'] == ['rice']

    def test_update_primary_counter_theme(self, loader):
        ld, fake = loader
        ld.update_primary_counter('Acme', theme_map={'friday': 'chinese'})
        counters = ld.get_counters_for_client('Acme')
        assert counters[0]['theme_map']['friday'] == 'chinese'
        # untouched fields preserved
        assert counters[0]['slot_counts']['veg_dry'] == 2

    def test_set_counters_too_many_rejected(self, loader):
        ld, _ = loader
        many = [_counter(f'C{i}', ['rice']) for i in range(MAX_COUNTERS + 1)]
        with pytest.raises(ValueError):
            ld.set_counters_for_client('Acme', 'multi', many)

    def test_delete_client(self, loader):
        ld, fake = loader
        ld.delete_client('Acme')
        assert 'Acme' not in [r['name'] for r in fake.rows('clients')]

    def test_delete_unknown_raises(self, loader):
        ld, _ = loader
        with pytest.raises(ValueError, match="Unknown client"):
            ld.delete_client('Ghost')


class TestLegacyFallback:
    """A client with no counters but legacy config tables still populated
    (pre-migration database) must still resolve via the fallback."""

    def test_legacy_tables_used_when_counters_empty(self):
        seed = {
            'clients': [{'name': 'Old', 'version': 1, 'counters': [],
                         'menu_category': 'cat_a'}],
            'menu_categories': [{'name': 'cat_a', 'slots': ['rice', 'dal', 'bread']}],
            'slot_count_overrides': [{'client_name': 'Old', 'slot': 'rice', 'count': 2}],
            'theme_overrides': [{'client_name': 'Old', 'day': 'tuesday', 'theme': 'south'}],
            'app_settings': [],
        }
        ld, _ = _make_loader(seed)
        counters = ld.get_counters_for_client('Old')
        assert len(counters) == 1
        assert set(counters[0]['categories']) == {'rice', 'dal', 'bread'}
        assert counters[0]['slot_counts']['rice'] == 2
        assert counters[0]['theme_map']['tuesday'] == 'south'
        assert ld.get_counter_mode('Old') == 'single'

    def test_no_counters_no_legacy_falls_back_to_default(self):
        seed = {'clients': [{'name': 'Bare', 'version': 1, 'counters': []}],
                'app_settings': []}
        ld, _ = _make_loader(seed)
        counters = ld.get_counters_for_client('Bare')
        assert len(counters) == 1
        # default counter has all toggleable categories
        assert 'veg_dry' in counters[0]['categories']


class TestValidate:
    def test_validate_ok(self, loader):
        ld, _ = loader
        ld.validate()

    def test_validate_rejects_bad_category(self):
        seed = {'clients': [{'name': 'X', 'version': 1,
                             'counters': [_counter('C', ['not_a_slot'])]}],
                'app_settings': []}
        ld, _ = _make_loader(seed)
        with pytest.raises(ValueError, match="unknown category"):
            ld.validate()


class TestHelpers:
    def test_dedupe_preserve_order(self):
        assert _dedupe_preserve_order(['a', 'b', 'a', 'c']) == ['a', 'b', 'c']

    def test_normalize_counter_clamps_and_keeps_constants(self):
        c = normalize_counter({
            'name': '', 'categories': ['veg_dry', 'bogus', 'white_rice', 'veg_dry'],
            'slot_counts': {'veg_dry': 9, 'rice': 'x'},
            'theme_map': {'monday': 'chinese', 'zzz': 'north'},
        }, 2)
        assert c['name'] == 'Counter 3'
        # bogus dropped + deduped; constants (white_rice) are now KEPT as
        # selectable categories.
        assert c['categories'] == ['veg_dry', 'white_rice']
        assert c['slot_counts']['veg_dry'] == _MAX_SLOT_COUNT   # clamped to the max
        assert 'white_rice' not in c['slot_counts']      # constants have no frequency
        assert c['theme_map']['monday'] == 'chinese'
        assert c['theme_map']['tuesday'] == DEFAULT_THEME_MAP['tuesday']

    def test_default_counter(self):
        c = default_counter(0)
        assert c['name'] == 'Counter 1'
        assert 'veg_dry' in c['categories']
        assert 'white_rice' not in c['categories']

    def test_normalize_city_valid_case_insensitive(self):
        assert normalize_city('bangalore') == 'Bangalore'
        assert normalize_city('  NCR ') == 'NCR'

    def test_normalize_city_unknown_or_blank(self):
        assert normalize_city('Atlantis') is None
        assert normalize_city('') is None
        assert normalize_city(None) is None


class TestCity:
    def test_create_with_city_and_read_back(self):
        ld, fake = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Acme', ['rice', 'dal'], city='pune')
        row = [r for r in fake.rows('clients') if r['name'] == 'Acme'][0]
        assert row['city'] == 'Pune'
        assert ld.get_client_city('Acme') == 'Pune'

    def test_create_without_city_is_none(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Acme', ['rice', 'dal'])
        assert ld.get_client_city('Acme') is None

    def test_set_client_city_updates(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Acme', ['rice', 'dal'], city='Chennai')
        ld.set_client_city('Acme', 'Hyderabad')
        assert ld.get_client_city('Acme') == 'Hyderabad'
        ld.set_client_city('Acme', 'not-a-city')
        assert ld.get_client_city('Acme') is None

    def test_get_city_unknown_client_raises(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        with pytest.raises(ValueError, match="Unknown client"):
            ld.get_client_city('Ghost')


class TestServeWeekends:
    def test_create_and_read_serve_weekends(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('WeCo', ['rice', 'dal'], serve_weekends=True)
        assert ld.get_client_serve_weekends('WeCo') is True
        assert ld.get_client('WeCo').serve_weekends is True

    def test_default_serve_weekends_false(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('WeCo', ['rice', 'dal'])
        assert ld.get_client_serve_weekends('WeCo') is False
        assert ld.get_client('WeCo').serve_weekends is False

    def test_set_serve_weekends(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('WeCo', ['rice', 'dal'])
        ld.set_client_serve_weekends('WeCo', True)
        assert ld.get_client_serve_weekends('WeCo') is True

    def test_get_client_configs_stamps_serve_weekends(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('WeCo', counter_mode='multi', counters=[
            _counter('A', ['rice']), _counter('B', ['dal']),
        ], serve_weekends=True)
        cfgs = ld.get_client_configs('WeCo')
        assert all(cfg.serve_weekends is True for _n, cfg in cfgs)


class TestWorkingDays:
    def test_default_working_days_none(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Quince', ['rice', 'dal'])
        assert ld.get_client_working_days('Quince') is None
        assert ld.get_client('Quince').working_days is None

    def test_set_and_read_working_days(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Quince', ['rice', 'dal'])
        ld.set_client_working_days(
            'Quince', ['Wednesday', 'thursday', 'FRIDAY'],
        )
        assert ld.get_client_working_days('Quince') == [
            'wednesday', 'thursday', 'friday',
        ]
        assert ld.get_client('Quince').working_days == [
            'wednesday', 'thursday', 'friday',
        ]

    def test_clear_working_days(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Quince', ['rice', 'dal'])
        ld.set_client_working_days('Quince', ['monday'])
        ld.set_client_working_days('Quince', None)
        assert ld.get_client_working_days('Quince') is None

    def test_get_client_configs_stamps_working_days(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Quince', counter_mode='multi', counters=[
            _counter('A', ['rice']), _counter('B', ['dal']),
        ])
        ld.set_client_working_days('Quince', ['wednesday', 'friday'])
        cfgs = ld.get_client_configs('Quince')
        assert all(
            cfg.working_days == ['wednesday', 'friday'] for _n, cfg in cfgs
        )


class TestItemCooldown:
    def test_create_and_read_cooldown(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('CoolCo', ['rice', 'dal'], item_cooldown_days=7)
        assert ld.get_client_item_cooldown_days('CoolCo') == 7

    def test_default_cooldown_is_none(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('CoolCo', ['rice', 'dal'])
        assert ld.get_client_item_cooldown_days('CoolCo') is None

    def test_set_and_clamp_cooldown(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('CoolCo', ['rice', 'dal'])
        ld.set_client_item_cooldown_days('CoolCo', 99)   # clamps to 60
        assert ld.get_client_item_cooldown_days('CoolCo') == 60
        ld.set_client_item_cooldown_days('CoolCo', -5)   # clamps to 0
        assert ld.get_client_item_cooldown_days('CoolCo') == 0

    def test_normalize_item_cooldown_days(self):
        from src.client.client_config import normalize_item_cooldown_days
        assert normalize_item_cooldown_days(14) == 14
        assert normalize_item_cooldown_days('21') == 21
        assert normalize_item_cooldown_days(None) is None
        assert normalize_item_cooldown_days('') is None
        assert normalize_item_cooldown_days('abc') is None

    def test_list_clients_with_city(self):
        ld, _ = _make_loader({'clients': [], 'app_settings': []})
        ld.create_client('Zeta', ['rice'], city='NCR')
        ld.create_client('Alpha', ['dal'], city='pune')
        ld.create_client('Beta', ['rice'])  # no city
        rows = ld.list_clients_with_city()
        assert [r['name'] for r in rows] == ['Alpha', 'Beta', 'Zeta']  # sorted
        by_name = {r['name']: r['city'] for r in rows}
        assert by_name == {'Alpha': 'Pune', 'Beta': None, 'Zeta': 'NCR'}

    def test_create_degrades_when_city_column_missing(self):
        """A pre-migration DB (no clients.city) must still create clients —
        the city is dropped rather than hard-failing the insert."""
        class _NoCityFake(FakeSupabase):
            def table(self, name):
                tbl = super().table(name)
                orig_insert = tbl.insert

                def _insert(payload):
                    rows = payload if isinstance(payload, list) else [payload]
                    if any('city' in r for r in rows):
                        exc = Exception("Could not find the 'city' column")
                        exc.code = "PGRST204"
                        raise exc
                    return orig_insert(payload)

                tbl.insert = _insert
                return tbl

        fake = _NoCityFake(seed={'clients': [], 'app_settings': []})
        with patch('src.client.client_config.get_supabase', return_value=fake):
            ld = ClientConfigLoader()
            ld.create_client('Acme', ['rice', 'dal'], city='Pune')
        row = [r for r in fake.rows('clients') if r['name'] == 'Acme'][0]
        assert 'city' not in row  # dropped on the fallback insert
        assert row['counters'][0]['categories']
