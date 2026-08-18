"""Tests for PoolBuilder."""

import pandas as pd
import pytest
from src.preprocessor.pool_builder import (
    PoolBuilder, BASE_SLOT_NAMES, _base_slot, _slot_num,
    _expand_slots_in_order,
)


def _make_ontology_df():
    """Create a minimal ontology DataFrame with at least 1 item per slot."""
    rows = []
    for slot in ['welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
                 'healthy_rice', 'dal', 'veg_gravy', 'veg_dry', 'nonveg_main',
                 'curd_side', 'dessert']:
        rows.append({'item': f'{slot}_item_1', 'course_type': slot, 'cuisine_family': 'indian', 'item_color': 'red'})
        rows.append({'item': f'{slot}_item_2', 'course_type': slot, 'cuisine_family': 'indian', 'item_color': 'green'})

    # sambar and rasam via sambar/rasam course_type
    rows.append({'item': 'sambar dal', 'course_type': 'sambar', 'cuisine_family': 'south_indian', 'item_color': 'yellow'})
    rows.append({'item': 'tomato rasam', 'course_type': 'sambar/rasam', 'cuisine_family': 'south_indian', 'item_color': 'orange'})
    rows.append({'item': 'sambar special', 'course_type': 'sambar/rasam', 'cuisine_family': 'south_indian', 'item_color': 'yellow'})

    # infused_water is its own category (Booking's detox-water list)
    rows.append({'item': 'lemon water', 'course_type': 'infused_water', 'cuisine_family': 'indian', 'item_color': 'yellow'})
    # a non-veg soup must survive in its own slot, unlike every other non-main
    rows.append({'item': 'chicken broth', 'course_type': 'nonveg_soup', 'cuisine_family': 'indian', 'item_color': 'brown', 'primary_protein': 'chicken'})

    return pd.DataFrame(rows)


class TestPoolBuilder:
    def test_all_base_slots_populated(self):
        from src.constants import DEFAULT_OFF_SLOTS
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        # Optional (default-off) stations may legitimately be empty in a
        # minimal ontology; every mandatory slot must be populated.
        for slot in BASE_SLOT_NAMES:
            if slot in DEFAULT_OFF_SLOTS:
                continue
            assert len(pools[slot]) > 0, f"Slot {slot} has no items"

    def test_curd_rice_pool_from_flag(self):
        # curd_rice is built off the is_curd_rice flag, not a course_type.
        df = _make_ontology_df()
        df['is_curd_rice'] = 0
        df.loc[df['course_type'] == 'curd_side', 'is_curd_rice'] = 1
        pools = PoolBuilder.build_pools(df)
        expected = set(df.loc[df['is_curd_rice'] == 1, 'item'])
        assert expected and set(pools['curd_rice']['item']) == expected

    def test_nonveg_items_excluded_from_veg_slots(self):
        # Non-veg items may appear ONLY in nonveg_main; a veg slot must never
        # serve a chicken/egg dish even if the ontology mis-files one.
        df = _make_ontology_df()
        extra = pd.DataFrame([
            {'item': 'chicken_starter_x', 'course_type': 'starter',
             'cuisine_family': 'north', 'item_color': 'red', 'primary_protein': 'chicken'},
            {'item': 'egg_rice_x', 'course_type': 'rice',
             'cuisine_family': 'north', 'item_color': 'yellow', 'is_egg_dish': 1},
            {'item': 'chicken_main_x', 'course_type': 'nonveg_main',
             'cuisine_family': 'north', 'item_color': 'red', 'primary_protein': 'chicken'},
        ])
        df = pd.concat([df, extra], ignore_index=True)
        pools = PoolBuilder.build_pools(df)
        assert 'chicken_starter_x' not in set(pools['starter']['item'])
        assert 'egg_rice_x' not in set(pools['rice']['item'])
        # ...but the non-veg slot keeps its non-veg item.
        assert 'chicken_main_x' in set(pools['nonveg_main']['item'])

    def test_combo_pools_union_components(self):
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        dal_items = set(pools['dal']['item'])
        rasam_items = set(pools['rasam']['item'])
        sambar_items = set(pools['sambar']['item'])
        assert set(pools['dal_rasam']['item']) == dal_items | rasam_items
        assert set(pools['sambar_rasam']['item']) == rasam_items | sambar_items
        assert set(pools['dal_sambar']['item']) == dal_items | sambar_items

    def test_sambar_rasam_split(self):
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        # 'tomato rasam' should be in rasam pool
        rasam_items = pools['rasam']['item'].tolist()
        assert 'tomato rasam' in rasam_items
        # 'sambar special' and 'sambar dal' should be in sambar pool
        sambar_items = pools['sambar']['item'].tolist()
        assert 'sambar dal' in sambar_items
        assert 'sambar special' in sambar_items

    def test_infused_water_is_its_own_slot_not_a_welcome_drink(self):
        """`infused_water` used to alias into the welcome_drink slot.

        It is a category in its own right now, so an infused-water slot must
        hold infused waters — filling it from the welcome-drink pool is not the
        category the client asked for — and the welcome-drink slot must not
        absorb them.
        """
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        assert 'lemon water' in pools['infused_water']['item'].tolist()
        assert 'lemon water' not in pools['welcome_drink']['item'].tolist()

    def test_a_non_veg_soup_survives_in_its_own_slot(self):
        """Non-veg dishes are dropped from every slot but the non-veg ones.

        `nonveg_soup` is a non-veg slot, so the guard has to test a SET; a bare
        `slot == 'nonveg_main'` check emptied the whole new category.
        """
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        assert 'chicken broth' in pools['nonveg_soup']['item'].tolist()
        for slot, pool in pools.items():
            if slot in ('nonveg_main', 'nonveg_soup'):
                continue
            assert 'chicken broth' not in pool['item'].tolist(), slot

    def test_empty_slot_raises(self):
        # Create df missing 'dessert'
        df = _make_ontology_df()
        df = df[df['course_type'] != 'dessert']
        with pytest.raises(ValueError, match="dessert"):
            PoolBuilder.build_pools(df)


class TestSlotHelpers:
    def test_base_slot_simple(self):
        assert _base_slot('veg_dry') == 'veg_dry'

    def test_base_slot_numbered(self):
        assert _base_slot('veg_dry__2') == 'veg_dry'

    def test_slot_num_simple(self):
        assert _slot_num('veg_dry') is None

    def test_slot_num_numbered(self):
        assert _slot_num('veg_dry__2') == 2

    def test_expand_slots_single(self):
        result = _expand_slots_in_order(['rice', 'veg_dry'], {'rice': 1, 'veg_dry': 1})
        assert result == ['rice', 'veg_dry']

    def test_expand_slots_multiple(self):
        result = _expand_slots_in_order(['rice', 'veg_dry'], {'rice': 1, 'veg_dry': 2})
        assert result == ['rice', 'veg_dry__1', 'veg_dry__2']

    def test_expand_slots_zero(self):
        result = _expand_slots_in_order(['rice', 'veg_dry'], {'rice': 0, 'veg_dry': 1})
        assert result == ['veg_dry']
