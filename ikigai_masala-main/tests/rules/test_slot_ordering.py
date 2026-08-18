"""Tests for the canonical slot display/config order (DISPLAY_SLOT_ORDER)."""

from ui.formatters import slot_sort_key
from src.constants import DISPLAY_SLOT_ORDER


class TestSlotOrdering:
    def test_canonical_sequence(self):
        seq = [
            'welcome_drink', 'soup', 'salad', 'bread', 'rice', 'white_rice',
            'veg_dry', 'veg_gravy', 'starter', 'dal', 'sambar', 'rasam',
            'dessert',
        ]
        keys = [slot_sort_key(s) for s in seq]
        assert keys == sorted(keys), f"not ascending: {list(zip(seq, keys))}"

    def test_white_rice_between_rice_and_veg_dry(self):
        assert slot_sort_key('rice') < slot_sort_key('white_rice') < slot_sort_key('veg_dry')

    def test_nonveg_sorts_last(self):
        others = [s for s in DISPLAY_SLOT_ORDER if s != 'nonveg_main']
        assert slot_sort_key('nonveg_main') > max(slot_sort_key(s) for s in others)

    def test_expanded_slot_id_uses_base_order(self):
        # veg_dry__2 sorts with veg_dry, not at the 999 fallback
        assert slot_sort_key('veg_dry__2') == slot_sort_key('veg_dry')

    def test_dessert_before_other_veg_and_nonveg(self):
        assert slot_sort_key('dessert') < slot_sort_key('healthy_rice')
        assert slot_sort_key('dessert') < slot_sort_key('nonveg_main')
