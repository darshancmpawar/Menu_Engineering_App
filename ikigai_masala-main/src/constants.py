"""
Shared constants for slot names, display labels, and other static config.

This module has zero heavy dependencies (no pandas, no ortools) so it can be
safely imported by lightweight layers like the UI without triggering the full
preprocessor import chain.
"""

from typing import Dict, List, Set

# ---------------------------------------------------------------------------
# Objective priority tiers (weighted-lexicographic)
# ---------------------------------------------------------------------------
# Hard rules are CP-SAT constraints, so a returned plan already satisfies all
# of them. Soft rules only shape the objective; to apply them *by priority*
# (rulebook §7 — never sacrifice a higher-priority soft rule to satisfy a
# lower one) each tier's weight is ~1000x the next. With realistic per-tier
# violation counts (tens, not thousands) a single higher-tier unit outweighs
# the entire pile of every lower tier, so one weighted solve behaves
# lexicographically without the cost of staged re-solves. The random
# tie-breaker (0..~1e3 per cell) sits below LOW.
OBJECTIVE_TIER_WEIGHTS: Dict[str, int] = {
    'theme': 10 ** 15,   # cuisine consistency — the top soft objective
    'high': 10 ** 12,    # rulebook high-priority soft rules
    'medium': 10 ** 9,   # rulebook medium-priority soft rules
    'low': 10 ** 6,      # rulebook low-priority soft rules
}

# ---------------------------------------------------------------------------
# Default weekday → cuisine-theme mapping (Mon..Fri)
# ---------------------------------------------------------------------------
# Single source of truth shared by the solver's global fallback
# (``_helpers.weekday_type``) and each client's default ``theme_map``
# (``client_config.DEFAULT_THEME_MAP``). Weekends / other days fall back to
# holiday / normal in ``weekday_type``.
DEFAULT_WEEKDAY_THEMES: Dict[str, str] = {
    'monday': 'mix',
    'tuesday': 'chinese',
    'wednesday': 'biryani',
    'thursday': 'south',
    'friday': 'north',
}

# ---------------------------------------------------------------------------
# Slot names
# ---------------------------------------------------------------------------

SLOT_SUFFIX_SEP = '__'

BASE_SLOT_NAMES: List[str] = [
    'welcome_drink', 'soup', 'salad', 'bread', 'rice',
    'veg_dry', 'veg_gravy', 'starter', 'dal', 'sambar', 'rasam', 'dessert',
    # other veg categories (shown after the mains)
    'healthy_rice', 'curd', 'curd_side', 'curd_rice',
    'dal_rasam', 'sambar_rasam', 'dal_sambar',
    # non-veg last
    'nonveg_main',
]

CONST_SLOTS: List[str] = ['white_rice', 'papad', 'pickle', 'chutney']

# Canonical order for BOTH the config editor and the rendered menu (table +
# Excel). Interleaves base and constant slots: welcome drink → soup → salad →
# breads/rices → veg dry → veg gravy → starter → dal/sambar/rasam → dessert →
# other veg categories → non-veg last. `slot_sort_key` and the slot editor both
# rank by this list, so config order and display order always match.
DISPLAY_SLOT_ORDER: List[str] = [
    'welcome_drink', 'soup', 'salad', 'bread', 'rice', 'white_rice',
    'veg_dry', 'veg_gravy', 'starter', 'dal', 'sambar', 'rasam', 'dessert',
    # other veg categories
    'healthy_rice', 'curd', 'curd_side', 'curd_rice',
    'dal_rasam', 'sambar_rasam', 'dal_sambar', 'papad', 'pickle', 'chutney',
    # non-veg last
    'nonveg_main',
]

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

# Ontology flags marking a dish that recurs like a staple **within one slot**:
# the SAME dish may be served every day there, the way steamed rice is. Such a
# dish is exempt from unique_items and from the item-cooldown ban, exactly like
# the plain-curd station — the 20-day no-repeat window governs ordinary dishes,
# not staples.
#
# The chicken kebab on a non-veg station is one of these. Treating it as an
# ordinary dish made a 5-dish counter unsatisfiable: only one kebab is eligible
# for a common-only client, so "a kebab every day" needed five distinct ones. It
# is a staple, not a variety slot.
#
# Keyed BY SLOT on purpose. ``is_tandoor`` also marks tandoor breads
# (butter_naan, butter_kulcha) and veg kebabs, and a flat flag list would have
# let butter naan repeat all week in the bread slot and skip its cooldown. The
# kebab is a staple of the non-veg station specifically.
REPEATABLE_ITEM_FLAGS_BY_SLOT: Dict[str, Set[str]] = {
    'nonveg_main': {'is_tandoor', 'is_tandoor_nonveg_dry'},
}

_TRUTHY = ('1', 'true', 'yes', 'y')


def repeatable_row(row, base_slot: str = None) -> bool:
    """True when *row* is a staple that may recur daily in *base_slot*.

    Matches on item name (:data:`REPEATABLE_ITEM_BASES`) or, when *base_slot* has
    an entry in :data:`REPEATABLE_ITEM_FLAGS_BY_SLOT`, on any of that slot's flag
    columns being set — so the ontology decides which dishes are staples and the
    slot decides where that applies. ``base_slot=None`` checks names only.
    """
    name = str(row.get('item', '') or '').strip().lower()
    if name in REPEATABLE_ITEM_BASES:
        return True
    for flag in REPEATABLE_ITEM_FLAGS_BY_SLOT.get(base_slot or '', ()):
        value = row.get(flag)
        if value is not None and str(value).strip().lower() in _TRUTHY:
            return True
    return False

# Proteins that mark a dish non-vegetarian (matched against the ontology's
# ``primary_protein`` column, plus the ``is_egg_dish`` flag). Single source of
# truth shared by the UI's red-dish tagging AND the pool builder's rule that
# non-veg items may appear only in the nonveg_main slot.
NONVEG_PROTEINS: Set[str] = {
    'chicken', 'egg', 'mutton', 'lamb', 'goat', 'fish', 'prawn', 'prawns',
    'shrimp', 'crab', 'keema', 'kheema', 'meat', 'seafood', 'beef', 'pork',
    'duck', 'turkey',
}

# The only slot a non-veg dish may be served in.
NONVEG_SLOT: str = 'nonveg_main'

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
