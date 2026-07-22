"""Tests for the curd-family categories (F1).

Covers: the plain-curd station pool (is_plain_curd flag), its repeatability
exemptions being registered, the Curd/Raita relabel, and the mutual-exclusion
validation between plain curd and curd/raita.
"""

import pandas as pd
import pytest

from src.constants import (
    BASE_SLOT_NAMES, DEFAULT_OFF_SLOTS, REPEATABLE_SLOTS, DISPLAY_SLOT_NAME,
    MUTUALLY_EXCLUSIVE_SLOT_GROUPS,
)
from src.preprocessor.pool_builder import PoolBuilder


def _ontology():
    rows = []
    for slot in ['welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
                 'healthy_rice', 'dal', 'veg_gravy', 'veg_dry', 'nonveg_main',
                 'curd_side', 'dessert']:
        rows.append({'item': f'{slot}_1', 'course_type': slot,
                     'cuisine_family': 'indian', 'item_color': 'red'})
        rows.append({'item': f'{slot}_2', 'course_type': slot,
                     'cuisine_family': 'indian', 'item_color': 'green'})
    rows.append({'item': 'sambar dal', 'course_type': 'sambar',
                 'cuisine_family': 'south_indian', 'item_color': 'yellow'})
    rows.append({'item': 'tomato rasam', 'course_type': 'rasam',
                 'cuisine_family': 'south_indian', 'item_color': 'orange'})
    return pd.DataFrame(rows)


class TestCurdCategoryRegistration:
    def test_curd_slot_selectable_off_by_default_and_repeatable(self):
        assert 'curd' in BASE_SLOT_NAMES
        assert 'curd' in DEFAULT_OFF_SLOTS       # selectable, off by default
        assert 'curd' in REPEATABLE_SLOTS        # repeats freely

    def test_display_labels(self):
        assert DISPLAY_SLOT_NAME['curd'] == 'Curd'
        assert DISPLAY_SLOT_NAME['curd_side'] == 'Curd / Raita'  # relabeled

    def test_curd_curd_raita_are_a_mutex_group(self):
        assert frozenset({'curd', 'curd_side'}) in MUTUALLY_EXCLUSIVE_SLOT_GROUPS


class TestCurdPool:
    def test_curd_pool_from_is_plain_curd_flag(self):
        df = _ontology()
        df['is_plain_curd'] = 0
        df.loc[df['course_type'] == 'curd_side', 'is_plain_curd'] = 1
        pools = PoolBuilder.build_pools(df)
        expected = set(df.loc[df['is_plain_curd'] == 1, 'item'])
        assert expected and set(pools['curd']['item']) == expected

    def test_curd_pool_empty_without_flag(self):
        # curd is default-off, so an ontology with no is_plain_curd column
        # yields an empty (but present) pool — not a build failure.
        pools = PoolBuilder.build_pools(_ontology())
        assert 'curd' in pools and len(pools['curd']) == 0


class TestCurdMutualExclusion:
    def _validate(self, cats):
        from src.client.client_config import ClientConfigLoader
        ClientConfigLoader._validate_counters(
            [{'name': 'C1', 'categories': cats}]
        )

    def test_curd_and_curd_raita_together_rejected(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            self._validate(['rice', 'curd', 'curd_side'])

    def test_curd_plus_curd_rice_allowed(self):
        self._validate(['rice', 'curd', 'curd_rice'])  # must not raise

    def test_curd_raita_plus_curd_rice_allowed(self):
        self._validate(['rice', 'curd_side', 'curd_rice'])  # must not raise
