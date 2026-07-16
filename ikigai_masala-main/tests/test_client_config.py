"""Tests for ClientConfigLoader (consolidated clients.counters model)."""

import pytest
from unittest.mock import patch

from tests.fake_supabase import FakeSupabase
from src.client.client_config import (
    ClientConfigLoader,
    normalize_counter,
    default_counter,
    _dedupe_preserve_order,
    DEFAULT_THEME_MAP,
    MAX_COUNTERS,
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

    def test_normalize_counter_clamps_and_drops(self):
        c = normalize_counter({
            'name': '', 'categories': ['veg_dry', 'bogus', 'white_rice', 'veg_dry'],
            'slot_counts': {'veg_dry': 9, 'rice': 'x'},
            'theme_map': {'monday': 'chinese', 'zzz': 'north'},
        }, 2)
        assert c['name'] == 'Counter 3'
        assert c['categories'] == ['veg_dry']            # bogus/const dropped, deduped
        assert c['slot_counts']['veg_dry'] == 3          # clamped to max 3
        assert c['theme_map']['monday'] == 'chinese'
        assert c['theme_map']['tuesday'] == DEFAULT_THEME_MAP['tuesday']

    def test_default_counter(self):
        c = default_counter(0)
        assert c['name'] == 'Counter 1'
        assert 'veg_dry' in c['categories']
        assert 'white_rice' not in c['categories']
