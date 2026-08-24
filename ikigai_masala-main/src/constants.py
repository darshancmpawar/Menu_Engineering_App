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
    'welcome_drink', 'infused_water', 'soup', 'nonveg_soup', 'salad',
    'bread', 'rice',
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
    'welcome_drink', 'infused_water', 'soup', 'nonveg_soup', 'salad',
    'bread', 'rice', 'white_rice',
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
# `infused_water` and `nonveg_soup` join the selectable-but-off set: they came
# from one client's menu (Booking.com) and switching them on for the other 50
# Bangalore counters would change every one of their plans.
DEFAULT_OFF_SLOTS: Set[str] = (
    {'curd', 'curd_rice', 'infused_water', 'nonveg_soup'}
    | set(COMBO_CATEGORIES)
)

# Slots whose items may repeat freely across the horizon (exempt from the
# unique-items constraint and the item-cooldown pre-filter). ``curd`` is a
# plain-curd station: the same plain curd is a daily staple, so it must not be
# starved by cooldown or forced to vary day-to-day by unique_items.
# `curd_rice` sits here with `curd` because curd rice is a STAPLE, the way
# steamed rice is: the same bowl every day is what the station serves, not a
# variety slot to rotate. It is therefore exempt from `unique_items` as well as
# the cooldown. (It was only cooldown-exempt before, so `unique_items` still
# demanded a distinct curd rice per day — ToastTab CHN has 2 and needed 3.)
REPEATABLE_SLOTS: Set[str] = {'curd', 'curd_rice'}

# Slots exempt from the item-cooldown ban ONLY — unlike REPEATABLE_SLOTS they
# KEEP unique_items, so they still serve distinct dishes within a week and only
# repeat once every distinct dish has been used ("once everything is done").
#
# The curd/raita side (``curd_side``), curd-rice station (``curd_rice``), ``soup``
# and ``healthy_rice`` are condiment/side slots with small pools (2-13 distinct
# dishes). The 20-day cooldown is a hard ban, so over a multi-week run it empties
# these pools and the solve goes INFEASIBLE — a fleet sweep found this drained
# ~18 counters by week 2-3. They are sides, not variety centrepieces, so the
# cross-week no-repeat window is wrong for them: dropping the hard ban lets the
# pool stay full, while unique_items still varies them within the week and the
# soft freshness objective rotates least-recently-served first across weeks — so
# they only repeat once the whole cycle of distinct dishes is used. Pan-India
# (global), mirroring how plain ``curd`` is already cooldown-exempt.
COOLDOWN_EXEMPT_SLOTS: Set[str] = {
    'curd_side', 'curd_rice', 'soup', 'healthy_rice',
    # Same argument as `soup`: sides with a small pool, where a hard 20-day ban
    # empties the slot before the cycle of distinct dishes is used up. They keep
    # unique_items, so they still vary within the week.
    'infused_water', 'nonveg_soup',
}

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

# Slots the day's theme must NOT hard-filter by cuisine. `dessert` and
# `curd_side` are here because a sweet or a raita does not have to match the
# day's region: serve the region's own when there is a good one, otherwise any
# is fine. Hard-narrowing them starved single-theme counters — L&T's all-south
# lunch saw 4 south desserts and 3 south raitas for a 5-day week and went
# INFEASIBLE, while Bangalore held 256 desserts. They are also in
# THEME_FALLBACK_SLOTS, which keeps "own region first" as a *preference*.
EXEMPT_FROM_CUISINE: Set[str] = {
    'welcome_drink', 'dal', 'sambar', 'rasam',
    'dal_rasam', 'sambar_rasam', 'dal_sambar',
    'starter', 'soup', 'salad', 'healthy_rice', 'curd_rice',
    'dessert', 'curd_side',
    # An infused water and a chicken broth carry no regional identity, so the
    # theme filter must not narrow them on a south/north/chinese day.
    'infused_water', 'nonveg_soup',
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

# The only slot a non-veg dish may be served in. `nonveg_main` is the primary
# one and stays a bare string for the callers that mean exactly it; the SET is
# what every guard should test, because a non-veg soup is also legitimately
# non-veg and would otherwise be dropped from its own slot by `_nonveg_mask`.
NONVEG_SLOT: str = 'nonveg_main'
NONVEG_SLOTS: Set[str] = {'nonveg_main', 'nonveg_soup'}

PULAO_SUBCATS: Set[str] = {
    'south_veg_pulao', 'north_simple_veg_pulao', 'north_rich_pulao',
    'millet_pulao', 'mixed_grain_pulao',
}

# Slots whose pool is NOT hard-filtered by cuisine but which still *prefer* the
# day's region: the solver samples the theme-matching items first and pays a
# fallback penalty when it has to reach outside. That is "fit its own region
# first, otherwise take one from another region" — the rule for `dessert` and
# `curd_side`, which have no regional obligation but should still read as local
# when the city carries a suitable dish.
THEME_FALLBACK_SLOTS: Set[str] = {'starter', 'veg_dry', 'dessert', 'curd_side'}

# Cities where EVERY client plans from the whole city list, ignoring the
# per-client `source_pools` narrowing (F5).
#
# Bangalore is here because the narrowing was costing far more than it bought:
# only 893 of its 4,349 rows carry `common`, the other 3,456 sit in eight
# client pools (healthineers 1,870 · continental 752 · cloudera 666 ·
# infineon 463 · zscalar 300 · amadeus 297 · computacenter 256 · icon 103), and
# most Bangalore clients have `source_pools = []` — so they were planning from
# roughly a fifth of the list while the rest was unreachable. An all-south
# counter like L&T saw 9 south desserts where the city holds 69.
#
# NCR is here for the same reason, and its list is even more lopsided: it has
# NO `common` pool at all — all 1,630 rows are tagged to one of eight sites
# (stryker 504 · carelon 443 · junglee games 353 · airtel noida 273 · sinch 247
# · siemens 223 · sael 203 · corning 124), with 93 untagged. Every live NCR
# client already planned from the whole list, but only by accident: their
# `source_pools = []` resolves to common-only, which matches zero NCR rows, and
# `filtered_menu_data` falls back to the full list when the subset comes out
# empty. Naming NCR here makes that intentional rather than incidental, and it
# also means a client who *does* set `source_pools` keeps the whole list instead
# of dropping to one site's dishes.
#
# Chennai joined for the same reason once its four new clients were wired: 191
# of its 673 rows sit in eight per-site pools (tata communications · rntbci ·
# wells fargo · ltm · world bank · icon · accenture · toast tab) while three of
# those four clients have `source_pools = []`. The effects were concrete and
# silent — World Bank could not see the 21 rows tagged "World Bank", and TCL,
# which serves a veg biryani in its first rice slot every day, could reach 4 of
# Chennai's 14 veg biryanis because the other 10 are tagged to sites. Same
# argument as Bangalore: these are dishes the same operation cooks in the same
# city, and ICON's own `source_pools` already names all eight tokens.
#
# Deliberately a city-level switch, not a per-client edit: it is reversible in
# one line and leaves every client row untouched. Remove a city from this set to
# restore per-client pools.
FULL_POOL_CITIES: Set[str] = {'bangalore', 'chennai', 'ncr'}

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
    'nonveg_soup': 'Non Veg Soup',
    'infused_water': 'Infused Water / Detox Drink',
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
