"""
Shared constants for slot names, display labels, and other static config.

This module has zero heavy dependencies (no pandas, no ortools) so it can be
safely imported by lightweight layers like the UI without triggering the full
preprocessor import chain.
"""

from typing import Dict, List, Set

# ---------------------------------------------------------------------------
# Slot names
# ---------------------------------------------------------------------------

SLOT_SUFFIX_SEP = '__'

BASE_SLOT_NAMES: List[str] = [
    'welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
    'healthy_rice', 'dal', 'sambar', 'rasam', 'veg_gravy', 'veg_dry',
    'nonveg_main', 'curd_side', 'dessert',
]

CONST_SLOTS: List[str] = ['white_rice', 'papad', 'pickle', 'chutney']

OUTPUT_SLOTS: List[str] = BASE_SLOT_NAMES + CONST_SLOTS

CONSTANT_ITEMS: Dict[str, str] = {
    'white_rice': 'steamed rice',
    'papad': 'Papad',
    'pickle': 'Pickle',
    'chutney': 'chutney',
}

EXEMPT_FROM_CUISINE: Set[str] = {
    'welcome_drink', 'dal', 'sambar', 'rasam', 'starter', 'soup', 'salad', 'healthy_rice',
}

REPEATABLE_ITEM_BASES: Set[str] = {'curd'}

PULAO_SUBCATS: Set[str] = {
    'south_veg_pulao', 'north_simple_veg_pulao', 'north_rich_pulao',
    'millet_pulao', 'mixed_grain_pulao',
}

THEME_FALLBACK_SLOTS: Set[str] = {'starter', 'veg_dry'}

DISPLAY_SLOT_NAME: Dict[str, str] = {
    'rice': 'Flavor Rice',
    'healthy_rice': 'Healthy Rice',
    'white_rice': 'White Rice',
    'welcome_drink': 'Welcome Drink',
    'soup': 'Soup',
    'salad': 'Salad',
    'veg_gravy': 'Veg Gravy',
    'veg_dry': 'Veg Dry',
    'nonveg_main': 'Nonveg Main',
    'curd_side': 'Curd Side',
}
