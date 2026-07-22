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
    'healthy_rice', 'dal', 'sambar', 'rasam',
    'dal_rasam', 'sambar_rasam', 'dal_sambar',
    'veg_gravy', 'veg_dry', 'nonveg_main',
    'curd', 'curd_side', 'curd_rice', 'dessert',
]

CONST_SLOTS: List[str] = ['white_rice', 'papad', 'pickle', 'chutney']

# Combination categories: ONE visible slot that alternates between two
# component course_types across the week — the majority variant fills most
# days, the minority the rest (see COMBO_MINORITY split). Keyed by the combo
# slot → (majority_course_type, minority_course_type).
COMBO_CATEGORIES: Dict[str, tuple] = {
    'dal_rasam':    ('dal', 'rasam'),     # 3 dal + 2 rasam over 5 days
    'sambar_rasam': ('rasam', 'sambar'),  # 3 rasam + 2 sambar over 5 days
    'dal_sambar':   ('dal', 'sambar'),    # 3 dal + 2 sambar over 5 days (dal majority)
}

# Categories that are selectable per client but OFF by default (a fresh client
# does not get them until an admin adds them in the editor): the optional
# plain-curd station, the curd-rice station, and the combination categories.
DEFAULT_OFF_SLOTS: Set[str] = {'curd', 'curd_rice'} | set(COMBO_CATEGORIES)

# Slots whose items may repeat freely across the horizon (exempt from the
# unique-items constraint and the item-cooldown pre-filter). ``curd`` is a
# plain-curd station: the same plain curd is a daily staple, so it must not be
# starved by cooldown or forced to vary day-to-day by unique_items.
REPEATABLE_SLOTS: Set[str] = {'curd'}

# The two yogurt-side categories are mutually exclusive on a single counter:
# a counter serves EITHER plain curd OR the curd/raita side, never both. The
# curd-rice station is independent and may be combined with either.
MUTUALLY_EXCLUSIVE_SLOT_GROUPS: List[frozenset] = [frozenset({'curd', 'curd_side'})]


def combo_minority_count(n_days: int) -> int:
    """Days the *minority* variant of a combination category gets over an
    ``n_days`` horizon. Anchored to 2-of-5 (so 5 days → 3 majority + 2 minority)
    and scaled for other lengths; the majority variant always gets at least as
    many days as the minority.
    """
    if n_days < 2:
        return 0
    minority = max(1, round(n_days * 2 / 5))
    return min(minority, n_days // 2)

CONSTANT_ITEMS: Dict[str, str] = {
    'white_rice': 'steamed rice',
    'papad': 'Papad',
    'pickle': 'Pickle',
    'chutney': 'chutney',
}

EXEMPT_FROM_CUISINE: Set[str] = {
    'welcome_drink', 'dal', 'sambar', 'rasam',
    'dal_rasam', 'sambar_rasam', 'dal_sambar',
    'starter', 'soup', 'salad', 'healthy_rice', 'curd_rice',
}

REPEATABLE_ITEM_BASES: Set[str] = {'curd'}

PULAO_SUBCATS: Set[str] = {
    'south_veg_pulao', 'north_simple_veg_pulao', 'north_rich_pulao',
    'millet_pulao', 'mixed_grain_pulao',
}

THEME_FALLBACK_SLOTS: Set[str] = {'starter', 'veg_dry'}

# Items that must never appear in a flavored-rice slot — plain/steamed rice
# variants belong in the CONST_SLOTS 'white_rice' slot instead.
RICE_EXCLUDE_ITEMS: Set[str] = {
    'steamed_rice', 'steamed rice',
    'white_rice', 'white rice',
    'steam rice',
    'plain_rice', 'plain rice',
}

DISPLAY_SLOT_NAME: Dict[str, str] = {
    'rice': 'Flavoured Rice',
    'bread': 'Indian Bread',
    'healthy_rice': 'Healthy Rice',
    'white_rice': 'White Rice',
    'welcome_drink': 'Welcome Drink',
    'soup': 'Soup',
    'salad': 'Salad',
    'veg_gravy': 'Veg Gravy',
    'veg_dry': 'Veg Dry',
    'nonveg_main': 'Nonveg Main',
    'curd': 'Curd',
    'curd_side': 'Curd / Raita',
    'curd_rice': 'Curd Rice',
    'dal_rasam': 'Dal / Rasam',
    'sambar_rasam': 'Sambar / Rasam',
    'dal_sambar': 'Dal / Sambar',
    'papad': 'Papad',
    'pickle': 'Pickle',
    'chutney': 'Chutney',
}
